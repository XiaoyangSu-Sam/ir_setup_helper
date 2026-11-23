from copy import deepcopy
from pathlib import Path

import pytest

from endurance.setup_files import parse_export, import_baseline, discover_exports, refresh_baseline, PARSER_VERSION
from endurance.storage import Store
from endurance.automatic import automatic_plan
from endurance.rules import load_rules
from endurance.snapshot_files import export_snapshot

CAR = 'ferrari296gt3'
TRACK = ('262', 'nurburgring combinedshortb')

# Synthetic representative markup, not a claimed captured real garage export.
HTML = b'''<html><head><title>Ferrari 296 GT3 setup: endurance</title></head>
<body><h2>FRONT:</h2><u>ARB blades:</u> 4 (45 degrees)<br>
<u>Total toe-in:</u> -3.0 mm<br><h2>REAR:</h2><u>ARB blades:</u> 15 degrees<br>
<u>Rear wing angle:</u> 4 degrees<br><u>Fuel level:</u> 103 L<br>
<h2>IN-CAR DIALS:</h2><u>Traction control setting:</u> 4 (TC)<br>
<script>Build Version: 9999.01.01.01</script></body></html>'''


def test_export_preserves_front_rear_units_and_missing_version():
    m = parse_export(HTML, 'official.htm', CAR, *TRACK)
    assert m['setup_flat']['Chassis.FrontBrakesLights.ArbBlades'] == '45 degrees'
    assert m['setup_flat']['Chassis.Rear.ArbBlades'] == '15 degrees'
    assert m['setup_flat']['Chassis.FrontBrakesLights.TotalToeIn'] == '-3.0 mm'
    assert m['build'] == 'unknown' and not m['official_verified']
    assert m['observed_wetness'] == [] and m['planned_conditions'] == 'dry'
    assert any(r['value'] == '4 (45 degrees)' for r in m['raw_fields'])
    assert '9999' not in str(m)


def test_reject_binary_wrong_car_layout_conflicts_and_large_export():
    for payload, name in [(b'\x03\x00\x00', 'baseline.sto'), (b'x' * 2_000_001, 'a.htm'),
                          (HTML.replace(b'296', b'488'), 'a.htm'),
                          (HTML + b'<div>Track: Monza</div>', 'a.htm'),
                          (HTML + b'<h2>FRONT:</h2>ARB blades: 90 degrees<br>', 'a.htm')]:
        with pytest.raises(ValueError):
            parse_export(payload, name, CAR, *TRACK)


def test_snapshot_reimport_preserves_fields_and_rejects_tampering(tmp_path):
    import json
    db = Store(tmp_path / "snapshot-destination")
    fields = {"Chassis.FrontBrakesLights.ArbBlades": "45 degrees", "Tires.SampleList": ["1.2", 3.4]}
    legacy = {"name": "旧设置", "car": CAR, "track_id": TRACK[0], "track": TRACK[1], "build": "2026.11.02.01",
              "setup_flat": fields, "validation_level": "已验证", "locally_validated": True}
    payload = export_snapshot(legacy)
    modern = import_baseline(db, payload, "snapshot.json", CAR, *TRACK)
    assert import_baseline(db, payload, "renamed.json", CAR, *TRACK) == modern
    import_baseline(db, json.dumps(legacy).encode(), "legacy.json", CAR, *TRACK)
    for version in db.versions():
        assert version["setup_flat"] == fields
        assert not version["locally_validated"]
    with pytest.raises(ValueError, match="校验失败"):
        import_baseline(db, payload.replace(b"45 degrees", b"99 degrees"), "changed.json", CAR, *TRACK)
    with pytest.raises(ValueError, match="车型或布局"):
        import_baseline(db, payload, "snapshot.json", CAR, "263", "different-layout")
    with pytest.raises(ValueError, match="可能损坏"):
        import_baseline(db, payload[:-10], "partial.json", CAR, *TRACK)
    assert len(db.versions()) == 2
    db.close()


def test_offline_ibt_and_export_imports_dedupe(make_ibt, tmp_path):
    db = Store(tmp_path / 'files')
    p = make_ibt()
    first = import_baseline(db, p.read_bytes(), p.name, CAR, *TRACK)
    assert import_baseline(db, p.read_bytes(), p.name, CAR, *TRACK) == first
    htmlid = import_baseline(db, HTML, 'baseline.htm', CAR, *TRACK)
    assert htmlid != first
    assert import_baseline(db, HTML, 'baseline.htm', CAR, *TRACK) == htmlid
    assert len(db.versions()) == 2
    assert len(list((db.root / 'setup_exports').glob('*.htm'))) == 1
    db.close()


def test_file_baseline_can_recommend_offline_with_known_version(make_ibt, tmp_path):
    db = Store(tmp_path / 'offline')
    db.import_file(make_ibt(front_arb=30))
    meta = parse_export(HTML, 'endurance.htm', CAR, *TRACK)
    rule = load_rules()['rules'][0]
    assert not automatic_plan(meta, rule, db.list_records())['ready']
    meta['build'] = 'test.1'  # Explicit supplied version, never borrowed from a different file.
    plan = automatic_plan(meta, rule, db.list_records())
    assert plan['ready'] and plan['current'] == 45 and plan['target'] == 30
    wet = deepcopy(meta)
    wet['setup_flat']['TiresAero.TireType.TireType'] = 'Wet'
    assert not automatic_plan(wet, rule, db.list_records())['ready']
    db.close()


def test_discover_exports_only_in_car_directory(tmp_path, monkeypatch):
    monkeypatch.setattr('endurance.setup_files.documents_dir', lambda: tmp_path)
    root = tmp_path / 'iRacing' / 'setups' / CAR
    root.mkdir(parents=True)
    (root / 'baseline.htm').write_bytes(HTML)
    (root / 'baseline.sto').write_bytes(b'binary')
    assert [p.name for p in discover_exports(CAR)] == ['baseline.htm']
    assert discover_exports('..') == []


REAL = Path(__file__).parent / 'fixtures' / 'ferrari296_real_export.htm'


def test_actual_export_maps_punctuated_heading_tc_and_separate_aero():
    m = parse_export(REAL.read_bytes(), REAL.name, CAR, *TRACK)
    flat = m['setup_flat']
    assert flat['Chassis.FrontBrakesLights.ArbBlades'] == '45 degrees'
    assert flat['Chassis.FrontBrakesLights.TotalToeIn'] == '-3.0 mm'
    assert flat['Chassis.InCarAdjustments.TcSetting'] == '4 (TC)'
    assert flat['Chassis.Rear.RearWingAngle'] == '3 degrees'
    assert flat['TiresAero.AeroBalanceCalc.RearWingAngle'] == '3 degrees'
    assert 'Chassis.RightRear.ArbBlades' not in flat
    assert m['exported_track'] == TRACK[1] and m['build'] == 'unknown'
    unknown = REAL.read_bytes() + b'<h2>UNSUPPORTED SECTION:</h2>ARB blades:<u>90 degrees</u><br>'
    assert parse_export(unknown, REAL.name, CAR, *TRACK)['setup_flat'] == flat


def test_repair_existing_file_preserves_id_build_preference_and_raw_bytes(tmp_path):
    db = Store(tmp_path / 'migration')
    rid = import_baseline(db, REAL.read_bytes(), REAL.name, CAR, *TRACK)
    original = db.versions()[0]
    broken = deepcopy(original)
    broken['meta'].pop('parser_version')
    broken['meta']['setup_flat'].pop('Chassis.FrontBrakesLights.ArbBlades')
    broken['setup_flat'] = broken['meta']['setup_flat']
    db.refresh_file_baseline(rid, {k: v for k, v in broken.items() if k not in {'id', 'created_at'}})
    db.set_setting('file-build:' + rid, 'test.1')
    repaired = refresh_baseline(db, db.versions()[0])
    assert repaired['id'] == rid and repaired['created_at'] == original['created_at']
    assert repaired['meta']['setup_flat']['Chassis.FrontBrakesLights.ArbBlades'] == '45 degrees'
    assert repaired['meta']['parser_version'] == PARSER_VERSION
    assert db.get_setting('file-build:' + rid) == 'test.1'
    assert len(db.versions()) == 1
    assert next((db.root / 'setup_exports').glob('*.htm')).read_bytes() == REAL.read_bytes()
    assert refresh_baseline(db, repaired) == repaired
    db.close()


def test_migration_refuses_modified_source(tmp_path):
    db = Store(tmp_path / 'bad-migration')
    import_baseline(db, REAL.read_bytes(), REAL.name, CAR, *TRACK)
    version = db.versions()[0]
    version['meta']['parser_version'] = 0
    next((db.root / 'setup_exports').glob('*.htm')).write_bytes(b'changed')
    with pytest.raises(ValueError, match='校验不符'):
        refresh_baseline(db, version)
    db.close()
