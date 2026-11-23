from copy import deepcopy
import struct

import pytest

from endurance.adjustment import fingerprint
from endurance.automatic import automatic_plan, choose_setup, observe_plan, validate_automatic_plan
from endurance.live_setup import decode_session, mapped_length, read_conditions, session_bounds
from endurance.rules import load_rules, parameter_number
from endurance.storage import Store


def examples(make_ibt, tmp_path):
    db = Store(tmp_path / 'automatic-db')
    before, _ = db.import_file(make_ibt(front_arb=45))
    db.import_file(make_ibt(name='after.ibt', front_arb=30))
    meta = db.record(before)['meta']
    rule = next(r for r in load_rules()['rules'] if r['parameter'] == 'Front ARB blades')
    return db, meta, rule


def test_automatic_target_uses_observed_value_not_inferred_step(make_ibt, tmp_path):
    db, meta, rule = examples(make_ibt, tmp_path)
    plan = automatic_plan(meta, rule, db.list_records())
    assert plan['target'] == 30 and plan['current'] == 45
    assert plan['steps'] is None and plan['tech_status'] == '未接通游戏检查结果'
    validate_automatic_plan(plan)
    smaller = deepcopy(meta)
    smaller['setup_flat'][rule['path']] = '30 degrees'
    assert not automatic_plan(smaller, rule, db.list_records())['ready']
    for key, value in [('build', 'other'), ('track_id', '263'), ('track', 'other')]:
        altered = deepcopy(meta)
        altered[key] = value
        assert not automatic_plan(altered, rule, db.list_records())['ready']
    db.close()


def test_automatic_checks_cannot_be_promoted_to_tech(make_ibt, tmp_path):
    db, meta, rule = examples(make_ibt, tmp_path)
    plan = automatic_plan(meta, rule, db.list_records())
    forged = {**plan, 'tech_status': 'Passed Tech'}
    forged['fingerprint'] = fingerprint(forged)
    with pytest.raises(ValueError):
        validate_automatic_plan(forged)
    with pytest.raises(ValueError):
        db.save_version({'numeric_plan': plan, 'locally_validated': True})
    with pytest.raises(ValueError):
        db.save_experiment({'workflow_version': 4, 'numeric_plan': plan, 'tech_status': 'Passed Tech'})
    oversized = {**plan, 'target': -100, 'max_change': 200}
    oversized['fingerprint'] = fingerprint(oversized)
    with pytest.raises(ValueError):
        validate_automatic_plan(oversized)
    plan['created_at'] = '2000-01-01T00:00:00+00:00'
    assert observe_plan(plan, db.list_records())['adopted']
    plan['created_at'] = '2099-01-01T00:00:00+00:00'
    assert not observe_plan(plan, db.list_records())['adopted']
    db.close()


def test_live_context_never_silently_uses_another_car(make_ibt, tmp_path):
    db, meta, rule = examples(make_ibt, tmp_path)
    car, track = meta['car'], (meta['track_id'], meta['track'])
    current = {'meta': meta}
    assert choose_setup(None, current, car, track)[1] == 'history'
    assert choose_setup(meta, current, car, track)[1] == 'live'
    assert choose_setup({**meta, 'car': 'other'}, current, car, track)[0] is None
    db.close()


def test_sdk_session_and_missing_conditions_are_bounded(make_ibt):
    blob = make_ibt().read_bytes()
    header = blob[:112]
    offset, length, _, _ = session_bounds(header)
    meta = decode_session(header, blob[offset:offset + length], header)
    assert meta['source_kind'] == 'live_sdk' and meta['car'] == 'ferrari296gt3'
    assert read_conditions(blob, header)['TrackWetness'] == 1
    assert read_conditions(blob, header)['FuelLevel'] == 81
    changed = bytearray(header)
    struct.pack_into('<i', changed, 12, 999)
    with pytest.raises(ValueError, match='正在更新'):
        decode_session(header, blob[offset:offset + length], changed)
    struct.pack_into('<i', changed, 52, -1)
    with pytest.raises(ValueError):
        mapped_length(changed)
    with pytest.raises(ValueError):
        read_conditions(blob[:120], header)
    missing = make_ibt(name='missing.ibt', missing=('TrackWetness',)).read_bytes()
    assert 'TrackWetness' not in read_conditions(missing, missing[:112])
    assert parameter_number('4 (TC)', 'Traction Control') == 4
    assert parameter_number('4 mm', 'Traction Control') is None
