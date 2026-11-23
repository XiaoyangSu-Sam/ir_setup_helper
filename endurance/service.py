"""Background file watcher independent of browser connection; never drives UI."""
from __future__ import annotations

from pathlib import Path
import threading
import time

from endurance.ibt import IBTError, IncompleteIBT
from endurance.analysis import compare_runs
from endurance.paths import telemetry_dir
from endurance.storage import Store
from endurance.trial import trial_role


class Watcher:
    def __init__(self, store: Store, interval: float = 15):
        self.store, self.interval = store, interval
        self.stop_event = threading.Event()
        self.guard = threading.Lock()
        self.seen = {}
        self.messages = {}
        self.status = "等待扫描"
        self.last_scan = None
        self.thread = None

    def start(self):
        if not self.thread or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._loop, name="telemetry-watch", daemon=True)
            self.thread.start()
        return self

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=30)

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                self.scan_once()
            except Exception as exc:
                self.status = f"扫描未完成：{type(exc).__name__}: {exc}"
            self.stop_event.wait(self.interval)

    def associate_experiments(self, record_id: str):
        """New compatible runs are candidates only; never auto-approve a setup."""
        new = self.store.record(record_id)
        meta = new["meta"]
        for experiment in self.store.experiments():
            if (experiment.get("status") not in {"待试跑", "新试跑待核对", "证据不足", "历史草案", "文件草案", "待应用"}
                    or experiment.get("car") != meta["car"] or experiment.get("track_id") != meta["track_id"]
                    or meta["start_utc"] < experiment["created_at"]
                    or record_id in experiment.get("before_records", [])):
                continue
            plan = experiment.get('numeric_plan') or {}
            if plan.get('schema') == 2 and trial_role(plan, new) != 'after':
                continue
            candidates = list(dict.fromkeys(experiment.get("candidate_after_records", []) + [record_id]))
            baseline_ids = experiment.get("before_records", [])
            if not baseline_ids:
                result = {"status": "证据不足", "conclusion": "已找到调整后候选，等待可比较的调整前记录。"}
            else:
                baseline = self.store.record(baseline_ids[0])
                result = compare_runs(baseline["meta"], meta, baseline["laps"], new["laps"])
            payload = {k: v for k, v in experiment.items() if k not in {"id", "created_at"}}
            payload.update(candidate_after_records=candidates, auto_comparison=result, status="新试跑待核对")
            self.store.save_experiment(payload, experiment["id"])

    def scan_once(self):
        if not self.guard.acquire(blocking=False):
            return
        try:
            if not self.store.get_setting("watch_enabled", True):
                self.status = "自动发现已暂停"
                return
            root = Path(self.store.get_setting("telemetry_path", str(telemetry_dir())))
            if not root.is_dir():
                self.status = "未找到遥测目录，请在数据页选择目录或开启游戏录制"
                return
            files = sorted(root.glob("*.ibt"), key=lambda p: p.stat().st_mtime, reverse=True)
            self.status = f"发现 {len(files)} 个文件；检查完成状态"
            imported = 0
            for path in files:
                if self.stop_event.is_set():
                    break
                stat = path.stat()
                signature = (stat.st_size, stat.st_mtime_ns)
                old = self.seen.get(str(path))
                if self.store.known_source(path):
                    continue
                # Recent/changing files require two observations and a quiet period.
                if time.time() - stat.st_mtime < 10 or (old is not None and old != signature):
                    self.seen[str(path)] = signature
                    self.messages[str(path)] = "正在记录／文件变化中，等待完成"
                    continue
                if old == signature and self.messages.get(str(path), "").startswith("无法导入"):
                    continue
                self.seen[str(path)] = signature
                try:
                    self.status = f"正在导入 {path.name}"
                    identifier, fresh = self.store.import_file(path)
                    if fresh:
                        self.associate_experiments(identifier)
                    imported += int(fresh)
                    self.messages[str(path)] = "已导入" if fresh else "已存在相同内容，未重复导入"
                except IncompleteIBT as exc:
                    self.messages[str(path)] = f"等待完整记录：{exc}"
                except (IBTError, OSError, ValueError) as exc:
                    self.messages[str(path)] = f"无法导入：{exc}"
                if imported >= 3:
                    break
            self.last_scan = time.time()
            self.status = f"监测中 · 找到 {len(files)} 个文件 · 本轮新增 {imported} 份"
        finally:
            self.guard.release()
