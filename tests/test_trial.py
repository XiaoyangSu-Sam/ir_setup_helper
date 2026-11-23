from copy import deepcopy

from endurance.adjustment import fingerprint
from endurance.automatic import automatic_plan
from endurance.rules import load_rules
from endurance.service import Watcher
from endurance.storage import Store
from endurance.trial import trial_defaults


def test_only_matching_future_target_becomes_after_candidate(make_ibt, tmp_path):
    store = Store(tmp_path / "trial")
    original, _ = store.import_file(make_ibt(front_arb=45))
    old_target, _ = store.import_file(make_ibt(name="evidence.ibt", front_arb=30))
    before = store.record(original)
    plan = automatic_plan(before["meta"], load_rules()["rules"][0], store.list_records())
    plan["created_at"] = "2026-01-01T00:00:00+00:00"
    plan["fingerprint"] = fingerprint(plan)
    store.save_experiment({"workflow_version": 4, "numeric_plan": plan, "tech_status": plan["tech_status"],
                           "status": "文件草案", "car": plan["car"], "track_id": plan["track_id"], "before_records": []})
    new_original, _ = store.import_file(make_ibt(name="original.ibt", front_arb=45, epoch=1893456000))
    target, _ = store.import_file(make_ibt(name="target.ibt", front_arb=30, epoch=1893457000, lap_seconds=58))
    wrong_version, _ = store.import_file(make_ibt(name="other.ibt", front_arb=30, epoch=1893459000, build="test.2"))
    watcher = Watcher(store)
    for record_id in (old_target, new_original, wrong_version, target):
        watcher.associate_experiments(record_id)
    saved = store.experiments()[0]
    assert saved["candidate_after_records"] == [target]
    assert saved["tech_status"] == "未接通游戏检查结果"
    matched = trial_defaults(plan, store.list_records())
    assert tuple(r["id"] for r in matched) == (new_original, target)
    store.close()


def test_pair_uses_recorded_settings_and_rejects_other_driver_or_changed_fuel():
    key = "Chassis.FrontBrakesLights.ArbBlades"
    fuel = "Chassis.Rear.FuelLevel"
    meta = {"car": "ferrari296gt3", "track_id": "262", "track": "nurburgring combinedshortb",
            "build": "test.1", "driver_id": "42"}
    baseline = {key: "45 degrees", fuel: "104.0 L"}
    plan = {**meta, "created_at": "2026-11-22", "parameter_path": key, "parameter": "Front ARB blades",
            "current": 45, "target": 30, "baseline_setup": baseline}
    before = {"id": "a", "meta": {**meta, "start_utc": "2026-11-22T10:00:00Z", "setup_flat": {
        **baseline, "UpdateCount": 1, "Chassis.LeftFront.RideHeight": "70.0 mm"}}}
    after = {"id": "b", "meta": {**meta, "start_utc": "2026-11-22T11:00:00Z", "setup_flat": {
        key: "30 degrees", fuel: "104 L", "UpdateCount": 2, "Chassis.LeftFront.RideHeight": "70.1 mm"}}}
    assert trial_defaults(plan, [after, before]) == (before, after)
    for field, value in ((fuel, "90 L"), ("Chassis.LeftFront.SpringRate", "210 N/mm")):
        modified = deepcopy(after)
        modified["meta"]["setup_flat"][field] = value
        assert trial_defaults(plan, [before, modified]) == (before, None)
    modified = deepcopy(after)
    modified["meta"]["driver_id"] = "43"
    assert trial_defaults(plan, [before, modified]) == (before, None)
