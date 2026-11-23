from copy import deepcopy
from pathlib import Path
import pytest

from endurance.automatic import automatic_plan, validate_automatic_plan, settings_fingerprint
from endurance.adjustment import fingerprint
from endurance.analysis import compatibility
from endurance.game_version import resolve_file_build, read_installed_build
from endurance.rules import load_rules
from endurance.setup_files import parse_export
from endurance.storage import Store

CURRENT = '2026.11.02.01'
SOURCE = '2026.10.01.01'
COMPONENT = '2026.09.25.02'


def actual_meta():
    content = (Path(__file__).parent / 'fixtures' / 'ferrari296_real_export.htm').read_bytes()
    meta = parse_export(content, 'ir_suggest.htm', 'ferrari296gt3', '262', 'nurburgring combinedshortb')
    detected = {'build': CURRENT, 'source': 'test installation', 'car_components': {
        'ferrari296gt3': {'build': COMPONENT, 'path': 'cars/ferrari296gt3/version.txt'}}}
    return resolve_file_build(meta, detected)


def test_reviewed_candidate_keeps_source_build_and_never_enables_lap_comparison(make_ibt, tmp_path):
    db = Store(tmp_path / 'review')
    rid, _ = db.import_file(make_ibt(front_arb=30, build=SOURCE))
    meta = actual_meta()
    plan = automatic_plan(meta, load_rules()['rules'][0], db.list_records())
    assert (plan['current'], plan['target']) == (45, 30)
    assert plan['parameter_evidence'] == 'reviewed_transfer'
    assert plan['evidence'][0]['build'] == SOURCE and plan['build'] == CURRENT
    assert plan['steps'] is None and plan['tech_status'] == '未接通游戏检查结果'
    validate_automatic_plan(plan)
    assert compatibility(meta, db.record(rid)['meta'])  # Build mismatch still blocks pace comparison.
    with pytest.raises(ValueError):
        db.save_version({'numeric_plan': plan, 'locally_validated': True})
    db.close()


@pytest.mark.parametrize('key,value', [('build', '2026.12.01.01'), ('car_component_build', '2026.11.02.01'),
                                     ('car_component_source', ''), ('track_id', '263'), ('track', 'other')])
def test_review_does_not_expand_to_unreviewed_context(make_ibt, tmp_path, key, value):
    db = Store(tmp_path / 'guard')
    db.import_file(make_ibt(front_arb=30, build=SOURCE))
    meta = actual_meta()
    meta[key] = value
    assert not automatic_plan(meta, load_rules()['rules'][0], db.list_records())['ready']
    db.close()


def test_related_arb_option_and_mutated_evidence_are_rejected(make_ibt, tmp_path):
    db = Store(tmp_path / 'guard-option')
    db.import_file(make_ibt(front_arb=30, build=SOURCE))
    meta = actual_meta()
    rule = load_rules()['rules'][0]
    plan = automatic_plan(meta, rule, db.list_records())
    meta['setup_flat']['Chassis.FrontBrakesLights.ArbOptions'] = 'Small'
    assert not automatic_plan(meta, rule, db.list_records())['ready']
    for field, value in [('review_id', 'wrong'), ('build', '2026.05.04.02'), ('matching_settings', {}), ('value', 15)]:
        tampered = deepcopy(plan)
        tampered['evidence'][0][field] = value
        tampered['fingerprint'] = fingerprint(tampered)
        with pytest.raises(ValueError):
            validate_automatic_plan(tampered)
    db.close()


def test_exact_build_evidence_has_priority(make_ibt, tmp_path):
    db = Store(tmp_path / 'priority')
    db.import_file(make_ibt(front_arb=40, build=SOURCE))
    db.import_file(make_ibt(name='current.ibt', front_arb=30, build=CURRENT))
    plan = automatic_plan(actual_meta(), load_rules()['rules'][0], db.list_records())
    assert plan['target'] == 30 and plan['parameter_evidence'] == 'same_build'
    assert all(e['build'] == CURRENT for e in plan['evidence'])
    db.close()


def test_component_probe_is_scoped_and_changes_invalidate_draft(tmp_path):
    (tmp_path / 'version_system.txt').write_text(CURRENT)
    car = tmp_path / 'cars' / 'ferrari296gt3'
    car.mkdir(parents=True)
    (car / 'version.txt').write_text(COMPONENT)
    assert read_installed_build([tmp_path])['car_components']['ferrari296gt3']['build'] == COMPONENT
    meta = actual_meta()
    modified = {**meta, 'car_component_build': '2026.11.03.01'}
    assert settings_fingerprint(meta) != settings_fingerprint(modified)
