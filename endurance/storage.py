"""Thread-safe single-process DuckDB catalog + atomic immutable Parquet files."""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import threading
import uuid

import duckdb
import polars as pl

from endurance.analysis import extract_laps
from endurance.ibt import file_hash, read_ibt, IncompleteIBT


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dump(value) -> str:
    def encode(obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        raise TypeError(f"Unsupported stored value: {type(obj).__name__}")
    return json.dumps(value, ensure_ascii=False, allow_nan=False, default=encode)


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "recordings").mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.ingest_lock = threading.Lock()
        self.db = duckdb.connect(str(self.root / "coach.duckdb"))
        self.db.execute("CREATE TABLE IF NOT EXISTS records (id VARCHAR PRIMARY KEY, imported_at VARCHAR, metadata VARCHAR, laps VARCHAR)")
        self.db.execute("CREATE TABLE IF NOT EXISTS sources (path VARCHAR PRIMARY KEY, size BIGINT, mtime BIGINT, record_id VARCHAR)")
        self.db.execute("CREATE TABLE IF NOT EXISTS preferences (key VARCHAR PRIMARY KEY, value VARCHAR)")
        self.db.execute("CREATE TABLE IF NOT EXISTS experiments (id VARCHAR PRIMARY KEY, created_at VARCHAR, payload VARCHAR)")
        self.db.execute("CREATE TABLE IF NOT EXISTS versions (id VARCHAR PRIMARY KEY, created_at VARCHAR, payload VARCHAR)")

    def close(self):
        with self.lock:
            self.db.close()

    def get_setting(self, key: str, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM preferences WHERE key=?", [key]).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO preferences VALUES (?,?)", [key, dump(value)])

    def known_source(self, path: Path) -> bool:
        stat = path.stat()
        with self.lock:
            row = self.db.execute("SELECT s.size,s.mtime,r.metadata FROM sources s JOIN records r ON r.id=s.record_id WHERE s.path=?", [str(path.resolve())]).fetchone()
        return bool(row and row[:2] == (stat.st_size, stat.st_mtime_ns) and json.loads(row[2]).get("schema_version", 0) >= 2)

    def import_file(self, path: Path, source_name: str | None = None) -> tuple[str, bool]:
        with self.ingest_lock:
            stat = path.stat()
            digest = file_hash(path)
            with self.lock:
                exists = self.db.execute("SELECT metadata FROM records WHERE id=?", [digest]).fetchone()
            if not exists or json.loads(exists[0]).get("schema_version", 0) < 2:
                recording = read_ibt(path)
                if source_name:
                    recording.metadata["source_name"] = Path(source_name).name
                df, laps = extract_laps(recording.samples, recording.metadata)
                for lap in laps:
                    lap["recording_id"] = digest
                recording.metadata["id"] = digest
                new_stat = path.stat()
                if (stat.st_size, stat.st_mtime_ns) != (new_stat.st_size, new_stat.st_mtime_ns):
                    raise IncompleteIBT("文件在校验与解析之间发生变化。")
                dest = self.root / "recordings" / f"{digest}.parquet"
                temp = dest.with_suffix(".parquet.partial")
                df.write_parquet(temp, compression="zstd")
                os.replace(temp, dest)
                with self.lock:
                    self.db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,?)",
                                    [digest, now(), dump(recording.metadata), dump(laps)])
            final = path.stat()
            if (stat.st_size, stat.st_mtime_ns) != (final.st_size, final.st_mtime_ns):
                raise IncompleteIBT("文件仍在变化，稍后重新核对。")
            with self.lock:
                self.db.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?,?)",
                                [str(path.resolve()), final.st_size, final.st_mtime_ns, digest])
            return digest, not bool(exists)

    def list_records(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT id,metadata,laps FROM records ORDER BY imported_at DESC").fetchall()
        records = [{"id": r[0], "meta": json.loads(r[1]), "laps": json.loads(r[2])} for r in rows]
        return sorted(records, key=lambda r: r["meta"]["start_utc"], reverse=True)

    def record(self, record_id: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT metadata,laps FROM records WHERE id=?", [record_id]).fetchone()
        if not row:
            raise KeyError("记录不存在")
        return {"id": record_id, "meta": json.loads(row[0]), "laps": json.loads(row[1])}

    def samples(self, record_id: str) -> pl.DataFrame:
        self.record(record_id)  # validate ID before constructing a path
        return pl.read_parquet(self.root / "recordings" / f"{record_id}.parquet")

    def save_experiment(self, payload: dict, experiment_id: str | None = None) -> str:
        if payload.get("workflow_version", 0) >= 4:
            from endurance.automatic import validate_automatic_plan
            validate_automatic_plan(payload.get("numeric_plan"))
            if payload.get("tech_status") != "未接通游戏检查结果" or payload.get("tech_report"):
                raise ValueError("自动检查适配器尚未取得 Tech 结果，不允许伪造通过状态。")
        elif payload.get("workflow_version", 0) >= 3:
            from endurance.adjustment import validate_plan, tech_passed
            validate_plan(payload.get("numeric_plan"))
            if payload.get("status") not in {"待游戏检查", "Tech未通过"} and not tech_passed(payload["numeric_plan"], payload.get("tech_report")):
                raise ValueError("必须先记录与此数值方案一致的 Passed Tech，才能进入试跑或效果验证。")
        identifier = experiment_id or uuid.uuid4().hex
        with self.lock:
            if experiment_id:
                old = self.db.execute("SELECT created_at FROM experiments WHERE id=?", [identifier]).fetchone()
                if not old:
                    raise KeyError("实验不存在")
                created = old[0]
            else:
                created = now()
            self.db.execute("INSERT OR REPLACE INTO experiments VALUES (?,?,?)", [identifier, created, dump(payload)])
        return identifier

    def experiments(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT id,created_at,payload FROM experiments ORDER BY created_at DESC").fetchall()
        return [{"id": r[0], "created_at": r[1], **json.loads(r[2])} for r in rows]

    def save_version(self, payload: dict) -> str:
        if (payload.get("numeric_plan") or {}).get("schema") == 2:
            from endurance.automatic import validate_automatic_plan
            validate_automatic_plan(payload["numeric_plan"])
            if payload.get("locally_validated"):
                raise ValueError("游戏 Tech 结果未接入，自动草案只能存为待验证版本。")
        elif payload.get("locally_validated") and payload.get("numeric_plan"):
            from endurance.adjustment import tech_passed
            if not tech_passed(payload["numeric_plan"], payload.get("tech_report")):
                raise ValueError("该数值方案的游戏 Tech 尚未核对，不能保存为已验证候选。")
        identifier = uuid.uuid4().hex
        with self.lock:
            self.db.execute("INSERT INTO versions VALUES (?,?,?)", [identifier, now(), dump(payload)])
        return identifier

    def refresh_file_baseline(self, identifier: str, payload: dict):
        """Update only derived file metadata; retain identity and original creation time."""
        with self.lock:
            row = self.db.execute('SELECT payload FROM versions WHERE id=?', [identifier]).fetchone()
            old = json.loads(row[0]) if row else {}
            if old.get('kind') != 'file_baseline' or any(payload.get(k) != old.get(k) for k in ('kind', 'file_hash', 'car', 'track_id', 'track')):
                raise ValueError('只能修复同一文件基准的派生解析结果。')
            self.db.execute('UPDATE versions SET payload=? WHERE id=?', [dump(payload), identifier])

    def versions(self, car: str | None = None, track_id: str | None = None) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT id,created_at,payload FROM versions ORDER BY created_at DESC").fetchall()
        result = [{"id": r[0], "created_at": r[1], **json.loads(r[2])} for r in rows]
        return [v for v in result if (car is None or v["car"] == car) and (track_id is None or v["track_id"] == track_id)]
