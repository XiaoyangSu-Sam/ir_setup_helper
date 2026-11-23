import os
from pathlib import Path
import time

import pytest

from endurance.ibt import IncompleteIBT
from endurance.service import Watcher
from endurance.storage import Store


def test_content_dedupe_and_restart(make_ibt, tmp_path):
    source = make_ibt()
    original = source.read_bytes()
    store = Store(tmp_path / "db")
    first, fresh = store.import_file(source)
    clone = tmp_path / "duplicate.ibt"
    clone.write_bytes(original)
    second, again = store.import_file(clone)
    assert first == second and fresh and not again
    assert len(store.list_records()) == 1
    store.set_setting("profile", {"race_hours": 4, "stint_minutes": 60})
    exp = store.save_experiment({"status": "待试跑", "feeling": "保持原话"})
    store.save_experiment({"status": "证据不足", "feeling": "保持原话"}, exp)
    version = store.save_version({"car": "ferrari296gt3", "track_id": "262", "name": "基准"})
    store.close()
    store = Store(tmp_path / "db")
    assert store.get_setting("profile")["stint_minutes"] == 60
    assert store.experiments()[0]["status"] == "证据不足"
    assert store.versions()[0]["id"] == version
    assert store.samples(first).height > 0
    assert source.read_bytes() == original
    store.close()


def test_incomplete_not_in_catalog(make_ibt, tmp_path):
    store = Store(tmp_path / "db")
    with pytest.raises(IncompleteIBT):
        store.import_file(make_ibt(finalized=False))
    assert store.list_records() == []
    store.close()


def test_watcher_waits_for_recent_file_then_imports(make_ibt, tmp_path):
    source = make_ibt()
    store = Store(tmp_path / "db")
    store.set_setting("telemetry_path", str(tmp_path))
    watcher = Watcher(store)
    watcher.scan_once()
    assert not store.list_records()
    os.utime(source, (time.time() - 60, time.time() - 60))
    watcher.scan_once()  # changed fingerprint -> wait one more observation
    watcher.scan_once()
    assert len(store.list_records()) == 1
    watcher.scan_once()
    assert len(store.list_records()) == 1
    store.close()


def test_source_path_traversal_rejected(tmp_path):
    store = Store(tmp_path / "db")
    with pytest.raises(KeyError):
        store.samples("../not-a-record")
    store.close()


def test_uploaded_name_preserved(make_ibt, tmp_path):
    store = Store(tmp_path / "db")
    identifier, _ = store.import_file(make_ibt(), source_name="my-reference.ibt")
    assert store.record(identifier)["meta"]["source_name"] == "my-reference.ibt"
    store.close()


def test_new_record_is_only_an_unconfirmed_experiment_candidate(make_ibt, tmp_path, monkeypatch):
    store = Store(tmp_path / "db")
    before, _ = store.import_file(make_ibt())
    # Fixture recordings date from 2023. The saved experiment predates them.
    monkeypatch.setattr("endurance.storage.now", lambda: "2020-01-01T00:00:00+00:00")
    exp = store.save_experiment({"status": "待试跑", "car": "ferrari296gt3", "track_id": "262", "before_records": [before]})
    after, _ = store.import_file(make_ibt(name="after.ibt", lap_seconds=58))
    watcher = Watcher(store)
    watcher.associate_experiments(after)
    watcher.associate_experiments(after)
    saved = next(e for e in store.experiments() if e["id"] == exp)
    assert saved["candidate_after_records"] == [after]
    assert saved["status"] == "新试跑待核对"
    assert saved["auto_comparison"]["status"] == "证据不足"
    assert not store.versions()
    store.close()


def test_feeling_experiment_can_receive_later_telemetry(make_ibt, tmp_path, monkeypatch):
    store = Store(tmp_path / "db")
    monkeypatch.setattr("endurance.storage.now", lambda: "2020-01-01T00:00:00+00:00")
    store.save_experiment({"status": "待试跑", "car": "ferrari296gt3", "track_id": "262", "before_records": [], "mode": "凭感觉"})
    record, _ = store.import_file(make_ibt())
    Watcher(store).associate_experiments(record)
    exp = store.experiments()[0]
    assert exp["candidate_after_records"] == [record] and not exp["before_records"]
    assert exp["auto_comparison"]["status"] == "证据不足"
    store.close()
