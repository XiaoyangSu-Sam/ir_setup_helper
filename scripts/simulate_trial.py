"""Replay a real setup with synthetic IBT samples in an isolated acceptance store.

Run from the project root with python -m scripts.simulate_trial.
"""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import struct
import time

import duckdb
import numpy as np
from streamlit.testing.v1 import AppTest
import yaml

from endurance.adjustment import fingerprint
from endurance.automatic import automatic_plan
from endurance.ibt import DTYPES, numeric
from endurance.paths import ROOT
from endurance.rules import load_rules, recommend, setup_difference
from endurance.service import Watcher
from endurance.setup_files import import_baseline
from endurance.storage import Store, dump


TICK_RATE = 60


def real_sources():
    review = json.loads((ROOT / "data" / "acceptance-parameter-review.json").read_text(encoding="utf-8"))
    with duckdb.connect(str(ROOT / "data" / "coach.duckdb"), read_only=True) as db:
        records = []
        for entry in review["evidence"]:
            row = db.execute("SELECT metadata FROM records WHERE id=?", [entry["record_id"]]).fetchone()
            if row is None:
                raise ValueError(f"Missing real evidence record {entry['record_id']}")
            records.append({"id": entry["record_id"], "meta": json.loads(row[0])})
        exports = list((ROOT / "data" / "setup_exports").glob("*.htm*"))
        # Resolve via the catalog so we do not accidentally pick a different export.
        for (raw,) in db.execute("SELECT payload FROM versions").fetchall():
            item = json.loads(raw)
            if item.get("name") == review["baseline_name"] and item.get("setup_flat") == review["baseline_setup"]:
                source = next(path for path in exports if path.stem == item["file_hash"])
                return review, records, source
    raise ValueError("The original Garage export for the saved review is missing")


def nested_setup(flat):
    nested = {}
    for key, value in flat.items():
        *parents, name = key.split(".")
        section = nested
        for part in parents:
            section = section.setdefault(part, {})
        section[name] = value
    return nested


def write_ibt(path, epoch, session, lap_times, fuel_l, offtrack_lap=None, corner_signals=None):
    """Write finalized v2 disk headers, session YAML, and typed sample rows."""
    ticks = np.rint(np.asarray(lap_times) * TICK_RATE).astype(int)
    ends = np.r_[0, np.cumsum(ticks)]
    total = ends[-1] + 1
    clock = np.arange(total) / TICK_RATE
    lap = np.repeat(np.arange(1, len(ticks) + 1), ticks)
    lap = np.r_[lap, len(ticks) + 1]
    progress = np.concatenate([np.arange(count) / count for count in ticks] + [np.zeros(1)])
    surface = np.full(total, 3)
    incidents = np.zeros(total)
    if offtrack_lap is not None:
        left = ends[offtrack_lap - 1] + ticks[offtrack_lap - 1] // 2
        surface[left:left + TICK_RATE] = 0
        incidents[left:] = 1

    phase = 2 * np.pi * progress
    speed, throttle, brake = 49 + 15 * np.cos(phase * 31), 0.58 + 0.35 * np.cos(phase * 31), np.maximum(0, -0.65 * np.cos(phase * 31))
    if corner_signals is not None:
        speed, throttle, brake = corner_signals(progress, speed, throttle, brake)
    channels = [
        ("SessionTime", 5, "s", clock),
        ("SessionNum", 2, "", np.zeros(total)),
        ("Lap", 2, "", lap),
        ("LapDistPct", 4, "%", progress),
        ("Speed", 4, "m/s", speed),
        ("Throttle", 4, "%", throttle),
        ("Brake", 4, "%", brake),
        ("SteeringWheelAngle", 4, "rad", 0.30 * np.sin(phase * 31)),
        ("FuelLevel", 4, "l", np.linspace(fuel_l, fuel_l - 3, total)),
        ("TrackTemp", 4, "C", np.full(total, 31)),
        ("AirTemp", 4, "C", np.full(total, 22)),
        ("TrackWetness", 2, "irsdk_TrackWetness", np.ones(total)),
        ("OnPitRoad", 1, "", np.zeros(total)),
        ("PlayerTrackSurface", 2, "irsdk_TrkLoc", surface),
        ("PlayerCarMyIncidentCount", 2, "", incidents),
        ("PlayerTireCompound", 2, "", np.zeros(total)),
        ("PlayerCarWeightPenalty", 4, "kg", np.zeros(total)),
        ("PlayerCarPowerAdjust", 4, "%", np.zeros(total)),
    ]
    dtype = np.dtype([(name, DTYPES[kind]) for name, kind, _, _ in channels])
    samples = np.empty(total, dtype=dtype)
    definitions = bytearray()
    for name, kind, unit, values in channels:
        samples[name] = values
        info = bytearray(144)
        struct.pack_into("<iii", info, 0, kind, dtype.fields[name][1], 1)
        info[16:16 + len(name)] = name.encode("ascii")
        info[112:112 + len(unit)] = unit.encode("ascii")
        definitions.extend(info)
    metadata = yaml.safe_dump(session).encode("utf-8")
    metadata_offset = 144 + len(definitions)
    header = bytearray(144)
    struct.pack_into("<10i", header, 0, 2, 1, TICK_RATE, 0, len(metadata), metadata_offset,
                     len(channels), 144, 1, dtype.itemsize)
    struct.pack_into("<i", header, 52, metadata_offset + len(metadata))
    struct.pack_into("<qddii", header, 112, epoch, 0, float(clock[-1]), len(ticks), total)
    with path.open("xb") as file:
        file.write(header)
        file.write(definitions)
        file.write(metadata)
        samples.tofile(file)
    # The production watcher intentionally waits for a quiet file.
    settled = time.time() - 15
    os.utime(path, (settled, settled))


def open_app(store_dir):
    os.environ["ENDURANCE_DATA_DIR"] = str(store_dir)
    os.environ["ENDURANCE_NO_WATCHER"] = "1"
    os.environ["ENDURANCE_NO_LIVE"] = "1"
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=45).run()
    next(r for r in app.radio if r.label == "工作区").set_value("试跑验证").run()
    assert not app.exception, app.exception
    return app


def main():
    reviewed, real_records, export = real_sources()
    output = ROOT / "outputs" / ("模拟试跑-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    telemetry = output / "synthetic_telemetry"
    telemetry.mkdir(parents=True, exist_ok=False)
    store_dir = output / "isolated_test_store"
    store = Store(store_dir)
    try:
        store.set_setting("telemetry_path", str(telemetry))
        version_id = import_baseline(store, export.read_bytes(), reviewed["baseline_name"],
                                     reviewed["car"], reviewed["track_id"], reviewed["track"])
        baseline = next(v for v in store.versions() if v["id"] == version_id)["meta"]
        assert baseline["setup_flat"] == reviewed["baseline_setup"]
        for key in ("build", "build_source", "build_assumption", "build_detection", "car_component_build", "car_component_source"):
            baseline[key] = reviewed.get(key)
        symptom = "入弯推头"
        rule = next(r for r in load_rules()["rules"] if symptom in r["symptoms"])
        plan = automatic_plan(baseline, rule, real_records)
        assert plan["ready"] and (plan["current"], plan["target"]) == (45, 30)
        plan["created_at"] = datetime.now(timezone.utc).isoformat()
        plan["fingerprint"] = fingerprint(plan)
        rec = recommend(baseline, symptom, "模拟验收：入弯时车头向外推", "", mode="凭感觉")
        rec.update(current=plan["current"], target=plan["target"])
        store.save_experiment({"workflow_version": 4, "numeric_plan": plan, "tech_status": plan["tech_status"],
                               "status": "文件草案", "car": plan["car"], "track_id": plan["track_id"],
                               "before_records": [], "recommendation": rec, "mode": "凭感觉",
                               "baseline_name": reviewed["baseline_name"], "simulation": True})

        context = real_records[0]["meta"]
        target_record = next(r for r in real_records if r["id"] == plan["evidence"][0]["record_id"])
        before_setup = plan["baseline_setup"]
        after_setup = {**before_setup, plan["parameter_path"]: target_record["meta"]["setup_flat"][plan["parameter_path"]]}
        fuel = numeric(before_setup["Chassis.Rear.FuelLevel"])
        shared = {
            "WeekendInfo": {"TrackID": int(plan["track_id"]), "TrackName": plan["track"],
                            "TrackDisplayName": context["track_name"], "TrackLength": f"{context['track_length_m'] / 1000:.4f} km",
                            "TrackVersion": context["track_version"], "BuildVersion": plan["build"]},
            "DriverInfo": {"DriverCarIdx": 0, "DriverCarFuelMaxLtr": fuel, "Drivers": [
                {"CarIdx": 0, "CarPath": plan["car"], "CarScreenName": "Ferrari 296 GT3 (SIMULATED)", "UserID": 0}]},
            "SplitTimeInfo": {"Sectors": [{"SectorNum": 0, "SectorStartPct": 0.0}]},
            "SimulationNotice": {"Samples": "SYNTHETIC - not a real iRacing session",
                                 "SetupSource": reviewed["baseline_name"], "ObservedTargetBuild": target_record["meta"]["build"],
                                 "SimulatedBuild": plan["build"]},
        }
        base_epoch = int((datetime.fromisoformat(plan["created_at"]) + timedelta(seconds=1)).timestamp())
        before_times = [487.4, 486.0, 486.8, 487.0]
        after_times = [484.9, 485.6, 484.6, 485.0, 477.0]
        write_ibt(telemetry / "SIMULATED_before_front_arb_45.ibt", base_epoch,
                  {**shared, "CarSetup": nested_setup(before_setup)}, before_times, fuel)
        watcher = Watcher(store)
        watcher.scan_once()
        assert len(store.list_records()) == 1
        assert not store.experiments()[0].get("candidate_after_records")
        write_ibt(telemetry / "SIMULATED_after_front_arb_30.ibt", base_epoch + 3600,
                  {**shared, "CarSetup": nested_setup(after_setup)}, after_times, fuel, offtrack_lap=5)
        watcher.scan_once()
        records = {r["meta"]["source_name"]: r for r in store.list_records()}
        before = records["SIMULATED_before_front_arb_45.ibt"]
        after = records["SIMULATED_after_front_arb_30.ibt"]
        assert before["meta"]["setup_flat"] == before_setup and after["meta"]["setup_flat"] == after_setup
        assert store.experiments()[0]["candidate_after_records"] == [after["id"]]
        assert len(setup_difference(before["meta"], after["meta"])) == 1
    finally:
        store.close()

    app = open_app(store_dir)
    assert any("已自动配对" in message.value for message in app.success)
    assert next(x for x in app.multiselect if x.label == "调整前驾驶段").value == [f"{before['id']}:1"]
    assert next(x for x in app.multiselect if x.label == "调整后驾驶段").value == [f"{after['id']}:1"]
    observed = next(metric for metric in app.metric if metric.label == "可比条件下，代表圈速变化").value
    assert observed == "-1.95 秒／圈", observed
    next(b for b in app.button if b.label == "保存本次数据对比").click().run()
    assert not app.exception, app.exception
    with duckdb.connect(str(store_dir / "coach.duckdb")) as db:
        exp = json.loads(db.execute("SELECT payload FROM experiments").fetchone()[0])
        assert db.execute("SELECT count(*) FROM records").fetchone()[0] == 2
    result = exp["result"]
    assert (result["before"]["valid"], result["after"]["valid"]) == (4, 4)
    assert (result["before"]["errors"], result["after"]["errors"]) == (0, 1)
    assert any(lap["complete"] and not lap["valid"] and lap["offtrack"] and abs(lap["duration_s"] - 477) < 0.01
               for lap in after["laps"])
    assert abs(result["groups"][0]["delta_s"] + 1.95) < 0.01
    assert exp["status"] == "证据不足" and exp["tech_status"] == "未接通游戏检查结果"
    report = {
        "dataset": "synthetic telemetry with real setup values",
        "baseline": reviewed["baseline_name"], "baseline_sha256": baseline["file_hash"],
        "setup_field_count": len(before_setup), "setup_difference": setup_difference(before["meta"], after["meta"]),
        "target_observed_in": target_record["meta"]["source_name"], "target_observed_build": target_record["meta"]["build"],
        "simulated_build": plan["build"], "before_times_s": before_times, "after_times_s": after_times,
        "offtrack_lap": 5, "displayed_difference": observed, "result": result, "tech_status": exp["tech_status"],
    }
    (output / "simulation-report.json").write_text(dump(report), encoding="utf-8")
    print(f"PASS: {observed}, valid laps 4 / 4, incident laps 0 / 1")
    print(output)


if __name__ == "__main__":
    main()
