from copy import deepcopy

import pytest

from endurance.analysis import compare_runs, endurance_coverage, extract_laps
from endurance.ibt import read_ibt
from endurance.rules import recommend, next_value


@pytest.fixture
def pair(make_ibt):
    r = read_ibt(make_ibt(laps=6))
    _, laps = extract_laps(r.samples, r.metadata)
    before = [l for l in laps if l["valid"]]
    after = deepcopy(before)
    for l in after:
        l["duration_s"] -= 1
    return r.metadata, before, after


def test_three_lap_threshold(pair):
    meta, a, b = pair
    assert compare_runs(meta, meta, a[:2], b, True, True)["status"] == "证据不足"
    assert compare_runs(meta, meta, a, b, True, True)["status"] == "初步改善"


@pytest.mark.parametrize("field,value", [("track_id", "263"), ("build", "new"), ("car", "other"), ("driver_id", "other")])
def test_incompatible_context(pair, field, value):
    meta, a, b = pair
    other = {**meta, field: value}
    assert compare_runs(meta, other, a, b, True, True)["status"] == "证据不足"


def test_different_conditions_not_pooled(pair):
    meta, a, b = pair
    for l in b:
        l["fuel_start_l"] = 20
    result = compare_runs(meta, meta, a, b, True, True)
    assert result["status"] == "证据不足"
    assert len(result["groups"]) == 2


def test_errors_override_fast_pace(pair):
    meta, a, b = pair
    bad = {**b[0], "valid": False, "offtrack": True}
    result = compare_runs(meta, meta, a, b + [bad], True, True)
    assert result["status"] == "初步恶化"
    assert result["after"]["errors"] == 1


def test_snapshot_is_not_per_lap_proof(pair):
    meta, a, b = pair
    assert compare_runs(meta, meta, a, b)["status"] == "证据不足"


def test_in_car_change_blocks_attribution(pair):
    meta, a, b = pair
    b[0]["in_car_changes"] = ["dcBrakeBias"]
    assert compare_runs(meta, meta, a, b, True, True)["status"] == "证据不足"


def test_endurance_is_not_race_duration_claim(pair):
    meta, a, _ = pair
    coverage = endurance_coverage(a, 104, 60)
    assert coverage["high_fuel_laps"] == 6
    assert coverage["low_fuel_laps"] == 0
    assert not coverage["stint_duration_observed"]


def test_recommendation_has_citation_and_no_guessed_numbers(pair):
    meta, _, _ = pair
    r = recommend(meta, "弯中推头", "车头不肯进弯", "左弯")
    assert r["available"] and r["target"] is None
    assert r["current"] == "30 degrees"
    assert r["source"].startswith("https://s100.iracing.com/")
    assert "待验证" in r["hypothesis"]
    assert r["feeling"] == "车头不肯进弯"


def test_only_verified_versioned_legal_steps():
    domain = {"verified": True, "build": "a", "allowed_values": [0, 15, 30, 45]}
    assert next_value(30, -1, domain, "a") == 15
    assert next_value(0, -1, domain, "a") is None
    assert next_value(30, -1, domain, "b") is None
    assert next_value(31, -1, domain, "a") is None


def test_other_car_and_wet_not_supported(pair):
    meta, _, _ = pair
    assert not recommend({**meta, "car": "other"}, "弯中推头", "", "")["available"]
    wet = deepcopy(meta)
    wet["setup_flat"]["TiresAero.TireType.TireType"] = "Wet"
    assert not recommend(wet, "弯中推头", "", "")["available"]


def test_slicks_on_wet_track_and_fixed_setup_are_blocked(pair):
    meta, _, _ = pair
    assert not recommend({**meta, "observed_wetness": [1, 3]}, "弯中推头", "", "")["available"]
    assert not recommend({**meta, "weekend_options": {"IsFixedSetup": 1}}, "弯中推头", "", "")["available"]


def test_parameter_domain_cannot_cross_cars(pair):
    meta, _, _ = pair
    domain = {"Front ARB blades": {"verified": True, "car": "other", "build": meta["build"], "allowed_values": [0, 15, 30]}}
    assert recommend(meta, "弯中推头", "", "", domain)["target"] is None
    domain["Front ARB blades"]["car"] = meta["car"]
    assert recommend(meta, "弯中推头", "", "", domain)["target"] == 15
