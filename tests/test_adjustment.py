from copy import deepcopy

import pytest

from endurance.adjustment import (allowed_range, validated_domain, numeric_plan, validate_plan, fingerprint,
                                  tech_report, tech_passed)
from endurance.knowledge import manual_context
from endurance.rules import load_rules
from endurance.storage import Store


def fixture_plan(value="30 degrees", values=(0, 15, 30, 45), baseline_passed=True):
    rule = load_rules()["rules"][0]
    meta = manual_context("ferrari296gt3", "262", "nurburgring combinedshortb", "test.1", True,
                          {rule["path"]: value})
    domain = validated_domain(rule["parameter"], meta["car"], meta["track_id"], meta["track"], meta["build"], list(values))
    return numeric_plan(meta, rule, domain, "原基准", 80, True, baseline_passed)


def test_exact_target_delta_step_and_rollback():
    p = fixture_plan()
    assert (p["current"], p["target"], p["delta"], p["steps"]) == (30, 15, -15, 1)
    assert "30" in p["rollback"]
    assert not tech_passed(p, None)
    validate_plan(p)


@pytest.mark.parametrize("value", ["0 degrees", "29 degrees", "30 mm", "", "NaN"])
def test_missing_units_bounds_or_unavailable_step_block_plan(value):
    with pytest.raises(ValueError):
        fixture_plan(value=value)


def test_baseline_must_have_been_checked():
    with pytest.raises(ValueError):
        fixture_plan(baseline_passed=False)


def test_decimal_steps_are_exact():
    assert allowed_range("-0.3", "0.3", "0.1") == [-.3, -.2, -.1, 0, .1, .2, .3]


@pytest.mark.parametrize("values", [("0", "1", "0.3"), ("0", "1", "0"), ("nan", "1", "1"), ("1", "0", "1"), ("0", "99999", ".001")])
def test_invalid_step_domains_are_rejected(values):
    with pytest.raises(ValueError):
        allowed_range(*values)


def test_integer_tc_domain():
    with pytest.raises(ValueError):
        validated_domain("Traction Control", "ferrari296gt3", "262", "nurburgring combinedshortb", "test.1", [1, 1.5, 2])


def test_pass_requires_actual_target_and_same_context():
    p = fixture_plan()
    with pytest.raises(ValueError):
        tech_report(p, "Passed Tech", "30 degrees", True, "")
    with pytest.raises(ValueError):
        tech_report(p, "Passed Tech", "15 degrees", False, "")
    r = tech_report(p, "Passed Tech", "15 degrees", True, "已核对")
    assert tech_passed(p, r) and "用户" in r["source"]
    changed = deepcopy(p)
    changed["fuel_l"] = 40
    changed["fingerprint"] = fingerprint(changed)
    assert not tech_passed(changed, r)


def test_target_mutation_rejected_even_if_hash_recomputed():
    p = fixture_plan()
    p["target"] = 100
    p["fingerprint"] = fingerprint(p)
    with pytest.raises(ValueError):
        validate_plan(p)


def test_failed_or_unchecked_tech_cannot_be_promoted(tmp_path):
    p = fixture_plan()
    failed = tech_report(p, "Failed Tech", "15 degrees", False, "Rear Ride Height 标红")
    assert not tech_passed(p, failed)
    store = Store(tmp_path / "db")
    payload = {"workflow_version": 3, "numeric_plan": p, "tech_report": failed, "status": "Tech未通过"}
    exp = store.save_experiment(payload)
    with pytest.raises(ValueError):
        store.save_experiment({**payload, "status": "待试跑"}, exp)
    with pytest.raises(ValueError):
        store.save_experiment({**payload, "status": "初步改善"}, exp)
    passed = tech_report(p, "Passed Tech", "15 degrees", True, "")
    store.save_experiment({**payload, "tech_report": passed, "status": "待试跑"}, exp)
    store.close()
