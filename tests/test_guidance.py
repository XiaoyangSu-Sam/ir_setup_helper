from copy import deepcopy

import pytest

from endurance.knowledge import manual_context, official_example, compare_examples, suggest_symptoms, knowledge
from endurance.rules import recommend, parameter_number


def context(**kwargs):
    return manual_context("ferrari296gt3", "262", "nurburgring combinedshortb", "test.1", **kwargs)


def test_manual_recommendation_has_no_telemetry_claim():
    r = recommend(context(dry_adjustable=True), "弯中推头", "车头转不过来", "左弯", facts=["不能泄漏的旧遥测"], mode="凭感觉")
    assert r["available"] and r["target"] is None
    assert r["context_source"] == "手动说明"
    assert "不能泄漏的旧遥测" not in r["facts"]
    assert r["interactions"] and r["parameter_knowledge"]["page"] == 14


def test_manual_conditions_and_data_only_evidence_are_required():
    assert not recommend(context(dry_adjustable=False), "弯中推头", "", "", mode="凭感觉")["available"]
    assert not recommend(context(dry_adjustable=True), "弯中推头", "", "", mode="凭数据")["available"]


def test_known_build_and_range_enable_manual_one_step():
    meta = context(dry_adjustable=True, setup_flat={"Chassis.Rear.RearWingAngle": "4 degrees"})
    domain = {"Rear Wing Angle": {"car": "ferrari296gt3", "build": "test.1", "verified": True, "allowed_values": [3, 4, 5]}}
    assert recommend(meta, "高速车尾不稳", "", "", domain, mode="凭感觉")["target"] == 5
    meta["build"] = "unknown"
    assert recommend(meta, "高速车尾不稳", "", "", domain, mode="凭感觉")["target"] is None


def test_units_and_natural_language_ambiguity():
    assert parameter_number("4 radians", "Rear Wing Angle") is None
    assert parameter_number("4 degrees", "Rear Wing Angle") == 4
    assert suggest_symptoms("没有推头") == []
    assert suggest_symptoms("基本上想带着速度的入弯都会推头") == ['入弯推头']
    assert suggest_symptoms("高速弯车尾一直滑") == ["高速车尾不稳"]
    assert len(suggest_symptoms("弯中推头，给油屁股就滑")) == 2


def example(**kwargs):
    args = dict(name="官方实例", car="ferrari296gt3", track_id="262", track="nurburgring combinedshortb", build="test.1",
                setup_flat={"Chassis.Rear.RearWingAngle": "4 degrees"}, source_note="用户从车库核对", confirmed=True)
    args.update(kwargs)
    return official_example(**args)


def test_official_label_is_not_personal_validation():
    a = example()
    assert not a["locally_validated"]
    assert "未独立" in a["source_verification"]
    with pytest.raises(ValueError):
        example(confirmed=False)
    with pytest.raises(ValueError):
        example(build="unknown")
    with pytest.raises(ValueError):
        example(setup_flat={})


def test_official_cochanges_never_prove_synergy():
    a, b = example(), example(setup_flat={"Chassis.Rear.RearWingAngle": "5 degrees"})
    result = compare_examples(a, b)
    assert len(result["rows"]) == 1 and "不证明" in result["message"]
    b["build"] = "other"
    assert not compare_examples(a, b)["rows"]


def test_every_parameter_and_coupling_has_a_source():
    k = knowledge()
    assert all(1 <= p["page"] <= 23 and p["up"] and p["down"] for p in k["parameters"])
    assert all(c["pages"] and c["checks"] for c in k["couplings"])
