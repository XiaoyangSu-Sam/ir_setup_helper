"""Exercise the actual Streamlit entry points with a real Garage export.

Run from the project root with python -m scripts.e2e_trial.
The output stores are independent of the active user library.
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import numpy as np
import streamlit as st
from streamlit.testing.v1 import AppTest

from endurance.automatic import automatic_plan
from endurance.game_version import detect_current_build, resolve_file_build
from endurance.ibt import file_hash, numeric
from endurance.paths import ROOT
from endurance.rules import load_rules
from endurance.setup_files import parse_export
from endurance.storage import Store
from scripts.simulate_trial import nested_setup, real_sources, write_ibt


def open_app(root):
    os.environ["ENDURANCE_DATA_DIR"] = str(root)
    os.environ["ENDURANCE_NO_WATCHER"] = "1"
    os.environ["ENDURANCE_NO_LIVE"] = "1"
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=45).run()


def action(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception, app.exception


def page(app, name):
    next(widget for widget in app.radio if widget.label == "工作区").set_value(name).run()
    assert not app.exception, app.exception


def upload_setup(app, name, content, mime):
    next(w for w in app.file_uploader if ".json" in w.allowed_type).upload(name, content, mime).run()
    action(app, "导入并用作基准")


def make_replay(folder, plan, metadata):
    folder.mkdir()
    before_setup = plan["baseline_setup"]
    target = f"{plan['target']:g} degrees"
    after_setup = {**before_setup, plan["parameter_path"]: target}
    fuel = numeric(before_setup["Chassis.Rear.FuelLevel"])
    session = {
        "WeekendInfo": {"TrackID": int(plan["track_id"]), "TrackName": plan["track"],
                        "TrackDisplayName": metadata["track_name"], "TrackLength": f"{metadata['track_length_m'] / 1000:.4f} km",
                        "TrackVersion": metadata["track_version"], "BuildVersion": plan["build"]},
        "DriverInfo": {"DriverCarIdx": 0, "DriverCarFuelMaxLtr": fuel,
                       "Drivers": [{"CarIdx": 0, "CarPath": plan["car"], "CarScreenName": "Ferrari 296 GT3 (SIMULATED)", "UserID": 0}]},
        "SimulationNotice": {"Samples": "SYNTHETIC - not a real iRacing session"},
        "SplitTimeInfo": {"Sectors": metadata["sectors"]},
    }
    start = int(datetime.fromisoformat(plan["created_at"]).timestamp()) + 2
    before, after = (folder / f"SIMULATED_{name}.ibt" for name in ("45deg", "30deg"))

    def signals(after_change):
        def model(progress, speed, throttle, brake):
            distance = progress * metadata['track_length_m']
            where = (distance >= 2770) & (distance <= 3180)
            points = [2770, 2800, 2840, 2870, 2920, 2975, 3010, 3150, 3180]
            speed[where] = np.interp(distance[where], points, [165, 166, 164, 158, 113, 89, 98, 144, 150]) / 3.6
            if after_change:
                speed[where] += np.interp(distance[where], points, [0, 0, 0, -2, -4, -1, 3, 5, 0]) / 3.6
            brake[where] = np.interp(distance[where], points, [0, 0, .25 if after_change else 0, .76, .32, .02, 0, 0, 0])
            throttle[where] = np.interp(distance[where], points, [.8, .6, .12, 0, .01, .18 if after_change else .08, .68, 1, 1])
            return speed, throttle, brake
        return model

    write_ibt(before, start, {**session, "CarSetup": nested_setup(before_setup)}, [487.4, 486, 486.8, 487], fuel, corner_signals=signals(False))
    write_ibt(after, start + 3600, {**session, "CarSetup": nested_setup(after_setup)}, [484.9, 485.6, 484.6, 485, 477], fuel,
              offtrack_lap=5, corner_signals=signals(True))
    return before, after


def main():
    reviewed, evidence, export = real_sources()
    output = ROOT / "outputs" / ("端到端验收-" + datetime.now(ZoneInfo("America/Toronto")).strftime("%Y%m%d-%H%M%S"))
    simulation_store, clean_store = output / "workflow", output / "reimport"
    source_name, source_bytes = reviewed["baseline_name"], export.read_bytes()
    # Only one actual evidence record is needed. Import its original IBT through the production reader.
    db = Store(simulation_store)
    exact_source = evidence[0]
    original_evidence, fresh = db.import_file(Path(exact_source["meta"]["source_path"]))
    assert fresh and original_evidence == exact_source["id"]
    db.close()

    app = open_app(simulation_store)
    upload_setup(app, source_name, source_bytes, "text/html")
    next(w for w in app.text_area if w.label == "保留我的原话").set_value("入弯时车头往外推").run()
    plain_language_recognized = any(b.label == "给我一个调整方案" for b in app.button)
    if not plain_language_recognized:
        next(w for w in app.text_area if w.label == "保留我的原话").set_value("入弯推头").run()
    downloads = {}
    actual_button = st.download_button

    def capture(label, data, *args, **kwargs):
        filename = kwargs.get("file_name")
        if filename in {"setup-candidate.json", "setup-experiment.txt"}:
            downloads[filename] = data
        return actual_button(label, data, *args, **kwargs)

    with patch.object(st, "download_button", capture):
        action(app, "给我一个调整方案")
    assert not app.warning or all("暂时无法" not in w.value for w in app.warning), app.warning
    assert any("45 → 30 deg" in m.value for m in app.markdown)
    candidate = downloads["setup-candidate.json"]
    (output / "setup-candidate.json").write_bytes(candidate)
    (output / "setup-experiment.txt").write_text(downloads["setup-experiment.txt"], encoding="utf-8")
    action(app, "保存这个方案")
    action(app, "打开试跑验证")
    assert any("等待可配对的记录" in item.value for item in app.info)
    db = Store(simulation_store)
    experiment, = db.experiments()
    plan = experiment["numeric_plan"]
    db.close()
    assert plan["parameter_evidence"] == "reviewed_transfer"

    before, after = make_replay(output / "synthetic_telemetry", plan, exact_source["meta"])
    page(app, "驾驶记录")
    duplicate = ("duplicate.ibt", before.read_bytes(), "application/octet-stream")
    broken = ("broken.ibt", after.read_bytes()[:-40], "application/octet-stream")
    app.file_uploader[0].set_value([(p.name, p.read_bytes(), "application/octet-stream") for p in (before, after)]
                                   + [duplicate, broken]).run()
    action(app, "导入选中的 IBT")
    assert any("已有同内容记录" in s.value and "duplicate" in s.value for s in app.success)
    assert any("broken.ibt" in e.value for e in app.error)
    page(app, "试跑验证")
    assert any("已自动配对" in msg.value for msg in app.success)
    metric = next(m for m in app.metric if m.label == "可比条件下，代表圈速变化")
    assert metric.value == "-1.95 秒／圈"
    wall, = app.get("iframe")
    payload = re.search(r'<script id="timing-wall-data" type="application/json">(.*?)</script>', wall.proto.srcdoc)
    timing = json.loads(payload[1])
    assert timing["simulated"] and timing["counts"] == [4, 4]
    assert len(timing["labels"]) == len(exact_source["meta"]["sectors"]) == 12
    assert all(reading["rank"] != "field" for reading in timing["reference"]["totals"])
    corner = next(window for sector in timing["reference"]["sectors"] for window in sector["windows"] if window["metrics"])
    braking, _, entry, _, exit_ = corner["metrics"]
    assert braking["pair"][1]["value"] > braking["pair"][0]["value"]
    assert entry["pair"][1]["value"] < entry["pair"][0]["value"]
    assert exit_["pair"][1]["value"] > exit_["pair"][0]["value"]
    for mode in ("reference", "best"):
        for side in range(2):
            assert abs(sum(pair[side]["value"] for pair in timing[mode]["columns"]) - timing[mode]["totals"][side]["value"]) < .001
    action(app, "保存本次数据对比")
    db = Store(simulation_store)
    saved, = db.experiments()
    records = db.list_records()
    assert len(records) == 3 and {r["id"] for r in records} == {original_evidence, file_hash(before), file_hash(after)}
    assert saved["status"] == "证据不足"
    assert saved["tech_status"] == "未接通游戏检查结果"
    result = saved["result"]
    assert (result["before"]["valid"], result["after"]["valid"], result["after"]["errors"]) == (4, 4, 1)
    base = parse_export(source_bytes, source_name, plan["car"], plan["track_id"], plan["track"])
    regenerated = automatic_plan(resolve_file_build(base, detect_current_build()), load_rules()["rules"][0], records)
    sim_used_as_evidence = any(e["record_id"] == file_hash(after) for e in regenerated.get("evidence", []))
    assert not sim_used_as_evidence
    db.close()

    clean = open_app(clean_store)
    upload_setup(clean, source_name, source_bytes, "text/html")
    upload_setup(clean, "setup-candidate.json", candidate, "application/json")
    upload_setup(clean, "duplicate-candidate.json", candidate, "application/json")
    assert any("已读取助手快照" in c.value for c in clean.caption)
    upload_setup(clean, "damaged-candidate.json", candidate.replace(b"30 degrees", b"99 degrees"), "application/json")
    assert any("校验失败" in m.value for m in clean.error)
    page(clean, "设置档案")
    archive = next(w for w in clean.selectbox if w.label == "历史版本")
    old_index = next(i for i, name in enumerate(archive.options) if source_name in name)
    archive.set_value(old_index).run()
    action(clean, "设为当前基准／回退到此版本")
    page(clean, "赛前工作台")
    rollback_changed = any(f"已读取文件基准：{source_name}" in msg.value for msg in clean.success)

    db = Store(clean_store)
    versions = db.versions()
    assert len(versions) == 2 and not db.list_records()
    restored = next(v for v in versions if v["meta"].get("source_kind") == "assistant_snapshot")
    expected = {**plan["baseline_setup"], plan["parameter_path"]: "30 degrees"}
    assert restored["setup_flat"] == expected
    assert restored["meta"]["origin"]["sha256"] == base["file_hash"]
    assert not restored["locally_validated"]
    db.close()
    report = {
        "baseline": source_name, "recognized_setup_fields": len(expected),
        "candidate_change": "Front ARB blades 45 → 30 degrees", "result": result,
        "checks": {
            "candidate_reimport": "passed", "duplicate_setup_deduplication": "passed",
            "damaged_setup_rejected": "passed", "duplicate_telemetry_deduplication": "passed",
            "truncated_telemetry_rejected": "passed", "automatic_pairing_and_save": "passed",
            "timing_wall_sectors": len(timing["labels"]), "timing_wall_rendered": "passed",
            "plain_language_entering_corner_push_recognized": plain_language_recognized,
            "archive_rollback_changes_workbench_baseline": rollback_changed,
            "simulated_telemetry_used_as_real_recommendation_evidence": sim_used_as_evidence,
        },
    }
    (output / "e2e-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    print(report["checks"])


if __name__ == "__main__":
    main()
