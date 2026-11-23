"""Bounded reader for iRacing IBT v1/v2 disk telemetry.

All channel definitions/units and array channels are preserved. Normalized scalar
channels are additive, never replacements for the original data. A final session
YAML setup snapshot is NOT evidence that each lap used those settings.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import re
import struct

import numpy as np
import polars as pl
import yaml


class IBTError(ValueError):
    pass


class IncompleteIBT(IBTError):
    pass


@dataclass
class Recording:
    metadata: dict
    samples: pl.DataFrame


CHANNELS = {
    "SessionTime": ("time_s", "s", 1),
    "SessionNum": ("session_num", "", 1),
    "SessionTick": ("tick", "", 1),
    "Lap": ("lap_number", "", 1),
    "LapDistPct": ("lap_dist_pct", "%", 1),
    "Speed": ("speed_kph", "m/s", 3.6),
    "Throttle": ("throttle", "%", 1),
    "Brake": ("brake", "%", 1),
    "SteeringWheelAngle": ("steering_deg", "rad", 180 / math.pi),
    "Gear": ("gear", "", 1),
    "RPM": ("rpm", "revs/min", 1),
    "LatAccel": ("lat_g", "m/s^2", 1 / 9.80665),
    "LongAccel": ("long_g", "m/s^2", 1 / 9.80665),
    "YawRate": ("yaw_rate_deg_s", "rad/s", 180 / math.pi),
    "FuelLevel": ("fuel_l", "l", 1),
    "TrackTemp": ("track_temp_c", "C", 1),
    "AirTemp": ("air_temp_c", "C", 1),
    "TrackWetness": ("wetness", "irsdk_TrackWetness", 1),
    "OnPitRoad": ("on_pit_road", "", 1),
    "PlayerTrackSurface": ("track_surface", "irsdk_TrkLoc", 1),
    "PlayerCarMyIncidentCount": ("incidents", "", 1),
    "PlayerTireCompound": ("tire_compound", "", 1),
    "PlayerCarWeightPenalty": ("weight_penalty_kg", "kg", 1),
    "PlayerCarPowerAdjust": ("power_adjust", "%", 1),
}
REQUIRED = {"time_s", "lap_number", "lap_dist_pct", "speed_kph"}
DTYPES = {0: "S1", 1: "?", 2: "<i4", 3: "<u4", 4: "<f4", 5: "<f8"}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def numeric(value) -> float | None:
    if value is None:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value))
    return float(match.group()) if match else None


def flatten(obj: dict, prefix: str = "") -> dict:
    result = {}
    for key, value in obj.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            result.update(flatten(value, name))
        else:
            result[name] = value
    return result


def is_simulated(meta: dict) -> bool:
    """Keep both newly marked and previously imported demo IBTs recognizable."""
    return bool(meta.get("simulated") or "(SIMULATED)" in str(meta.get("car_name", "")).upper()
                or str(meta.get("source_name", "")).upper().startswith("SIMULATED_"))


def _metadata(session: dict, start_epoch: int, tick_rate: int, channels: list[dict]) -> dict:
    weekend = session.get("WeekendInfo", {}) or {}
    driver_info = session.get("DriverInfo", {}) or {}
    drivers = driver_info.get("Drivers", []) or []
    driver = next((d for d in drivers if d.get("CarIdx") == driver_info.get("DriverCarIdx")), {})
    setup = session.get("CarSetup", {}) or {}
    track_length = numeric(weekend.get("TrackLength"))
    if track_length and "km" in str(weekend.get("TrackLength")):
        track_length *= 1000
    return {
        "schema_version": 2,
        "start_utc": datetime.fromtimestamp(start_epoch, timezone.utc).isoformat(),
        "tick_rate": tick_rate,
        "car": driver.get("CarPath", "unknown"),
        "car_name": driver.get("CarScreenName", "未知车型"),
        "driver_id": str(driver.get("UserID", "unknown")),
        "driver_car_idx": driver_info.get("DriverCarIdx"),
        "simulated": bool(session.get("SimulationNotice")),
        "fuel_capacity_l": numeric(driver_info.get("DriverCarFuelMaxLtr")),
        "track_id": str(weekend.get("TrackID", "unknown")),
        "track": weekend.get("TrackName", "unknown"),
        "track_name": weekend.get("TrackDisplayName", weekend.get("TrackName", "未知赛道")),
        "track_config": weekend.get("TrackConfigName", ""),
        "track_length_m": track_length,
        "build": weekend.get("BuildVersion", "unknown"),
        "track_version": weekend.get("TrackVersion", "unknown"),
        "session_id": str(weekend.get("SessionID", "")),
        "subsession_id": str(weekend.get("SubSessionID", "")),
        "sessions": session.get("SessionInfo", {}).get("Sessions", []),
        "sectors": session.get("SplitTimeInfo", {}).get("Sectors", []),
        "environment": {k: v for k, v in weekend.items() if k.startswith(("Track", "Weather"))},
        "weekend_options": weekend.get("WeekendOptions", {}),
        "setup": setup,
        "setup_flat": flatten(setup),
        "setup_scope": "文件末态快照；各圈是否一致待核实",
        "channels": channels,
        "missing_channels": [],
        "warnings": [],
    }


def read_ibt(path: str | Path) -> Recording:
    path = Path(path)
    before = path.stat()
    if before.st_size < 144:
        raise IncompleteIBT("文件头不完整，等待 iRacing 完成记录。")
    with path.open("rb") as f:
        header = f.read(144)
        version, _, tick_rate, _, slen, soff, nvars, voff, nbuf, row_size = struct.unpack_from("<10i", header)
        data_offset = struct.unpack_from("<i", header, 52)[0]
        epoch, start, end, _, records = struct.unpack_from("<qddii", header, 112)
        if version not in {1, 2} or not 1 <= tick_rate <= 1000 or not 1 <= nvars <= 10000:
            raise IBTError("不支持的 IBT 文件头或变量数。")
        if not 1 <= nbuf <= 4 or not 1 <= row_size <= 4_000_000:
            raise IBTError("无效的 IBT 缓冲区。")
        if not 0 < slen <= 16_000_000 or soff < 144 or voff < 144:
            raise IBTError("无效的会话或变量表偏移。")
        if max(soff + slen, voff + 144 * nvars) > before.st_size:
            raise IncompleteIBT("会话或变量表尚未写完。")
        # Finalized disk header is essential; stable size alone doesn't mean closed.
        if records <= 0 or end <= start:
            raise IncompleteIBT("磁盘记录尚未封口，退回车库结束本次记录后再试。")
        if data_offset < max(soff + slen, voff + nvars * 144):
            raise IBTError("样本区与会话信息重叠。")
        if data_offset + records * row_size != before.st_size:
            raise IncompleteIBT("样本数与文件长度不符：文件未写完或已损坏。")
        f.seek(soff)
        raw_yaml = f.read(slen).rstrip(b"\0")
        try:
            text = raw_yaml.decode("utf-8")
        except UnicodeDecodeError:
            text = raw_yaml.decode("cp1252", errors="replace")
        try:
            session = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise IBTError("会话 YAML 无法解析。") from exc
        if not isinstance(session, dict):
            raise IBTError("缺少会话信息。")
        channels, names, formats, offsets = [], [], [], []
        f.seek(voff)
        for _ in range(nvars):
            raw = f.read(144)
            typ, offset, count = struct.unpack_from("<iii", raw)
            name = raw[16:48].split(b"\0")[0].decode("ascii", errors="replace")
            desc = raw[48:112].split(b"\0")[0].decode("cp1252", errors="replace")
            unit = raw[112:144].split(b"\0")[0].decode("ascii", errors="replace")
            if typ not in DTYPES or not name or name in names or not 1 <= count <= 10000:
                raise IBTError("变量定义无效或重复。")
            base = np.dtype(DTYPES[typ])
            if offset < 0 or offset + count * base.itemsize > row_size:
                raise IBTError(f"变量 {name} 超出样本边界。")
            channels.append({"name": name, "type": typ, "count": count, "unit": unit, "description": desc})
            names.append(name)
            formats.append(base if count == 1 else (base, (count,)))
            offsets.append(offset)
    dtype = np.dtype({"names": names, "formats": formats, "offsets": offsets, "itemsize": row_size})
    raw = np.memmap(path, mode="r", offset=data_offset, dtype=dtype, shape=(records,))
    try:
        columns = {}
        for channel in channels:
            name = channel["name"]
            arr = np.array(raw[name], copy=True)
            if channel["type"] == 0:
                columns[name] = [bytes(x).decode("cp1252", "replace").rstrip("\0") for x in arr]
            else:
                columns[name] = arr
        df = pl.DataFrame(columns)
    finally:
        del raw
    meta = _metadata(session, epoch, tick_rate, channels)
    by_name = {c["name"]: c for c in channels}
    expressions = []
    for source, (target, expected_unit, factor) in CHANNELS.items():
        if source not in by_name or by_name[source]["count"] != 1:
            meta["missing_channels"].append(target)
            continue
        actual_unit = by_name[source]["unit"]
        if actual_unit != expected_unit:
            meta["warnings"].append(f"{source} 单位 {actual_unit!r} 未匹配 {expected_unit!r}，不参与计算。")
            meta["missing_channels"].append(target)
            continue
        expressions.append((pl.col(source).cast(pl.Float64) * factor).alias(target))
    df = df.with_columns(expressions).with_row_index("sample_index")
    if not REQUIRED.issubset(df.columns):
        raise IBTError("缺少或无法换算核心通道：" + ", ".join(sorted(REQUIRED - set(df.columns))))
    if meta["track_length_m"]:
        df = df.with_columns((pl.col("lap_dist_pct") * meta["track_length_m"]).alias("distance_m"))
    else:
        raise IBTError("会话没有可靠赛道长度，无法进行距离分析。")
    for col in REQUIRED:
        if not np.isfinite(df[col].to_numpy()).all():
            raise IBTError(f"核心通道 {col} 含非有限数值。")
    after = path.stat()
    if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
        raise IncompleteIBT("读取过程中记录发生变化，稍后重试。")
    meta["observed_wetness"] = sorted({int(x) for x in df["wetness"].to_list() if x is not None and math.isfinite(x)}) if "wetness" in df.columns else []
    meta.update(source_path=str(path.resolve()), source_name=path.name, source_size=before.st_size,
                source_mtime_ns=before.st_mtime_ns, record_count=records,
                normalized_units={v[0]: {"speed_kph": "km/h", "steering_deg": "deg", "lat_g": "g", "long_g": "g"}.get(v[0], v[1]) for v in CHANNELS.values()})
    return Recording(meta, df)
