"""Local maintenance CLI, also useful for reproducible acceptance reports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from endurance.analysis import pace_summary
from endurance.paths import data_dir, telemetry_dir
from endurance.storage import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["import", "summary"])
    parser.add_argument("--folder", type=Path, default=telemetry_dir())
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    store = Store(data_dir())
    report = []
    try:
        if args.command == "import":
            for path in sorted(args.folder.glob("*.ibt"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    identifier, fresh = store.import_file(path)
                    r = store.record(identifier)
                    summary = pace_summary(r["laps"])
                    item = {"file": path.name, "fresh": fresh, "samples": r["meta"]["record_count"],
                            "car": r["meta"]["car"], "track": r["meta"]["track"], **summary}
                except (ValueError, OSError) as exc:
                    item = {"file": path.name, "error": str(exc)}
                report.append(item)
                print(json.dumps(item, ensure_ascii=False), flush=True)
        else:
            report = [{"file": r["meta"]["source_name"], **pace_summary(r["laps"])} for r in store.list_records()]
            print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        store.close()


if __name__ == "__main__":
    main()
