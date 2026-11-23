"""Concrete, bounded adjustments with a separate, attributable game Tech result."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import math

from endurance.rules import next_value, parameter_number

UNITS = {"Front ARB blades": "deg", "Front Total Toe-In": "mm", "Traction Control": "档", "Rear Wing Angle": "deg"}


def allowed_range(low: str, high: str, step: str) -> list[float]:
    try:
        a, b, s = map(Decimal, (low.strip(), high.strip(), step.strip()))
        if not all(v.is_finite() for v in (a, b, s)) or s <= 0 or b <= a:
            raise ValueError("需要有限的最小值 < 最大值，且步长 > 0。")
        n = (b - a) / s
        if n != n.to_integral_value() or n > 2000:
            raise ValueError("上下限必须能按步长对齐，且最多 2001 个档位；不规则档位请填写完整列表。")
        return [float(a + i * s) for i in range(int(n) + 1)]
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("请输入游戏显示的数字上下限和步长。") from exc


def validated_domain(parameter: str, car: str, track_id: str, track: str, build: str, values: list[float]) -> dict:
    if parameter not in UNITS or not build.strip() or build.strip() == "unknown":
        raise ValueError("需要支持的参数和实际游戏版本。")
    if len(values) < 2 or len(values) > 2001 or not all(type(v) in (int, float) and math.isfinite(v) for v in values):
        raise ValueError("至少需要两个有限的合法档位。")
    if parameter == "Traction Control" and any(v != int(v) for v in values):
        raise ValueError("TC 档位必须为整数。")
    if len(set(values)) != len(values):
        raise ValueError("可选值不应重复。")
    return {"car": car, "track_id": track_id, "track": track, "build": build.strip(), "unit": UNITS[parameter],
            "verified": True, "allowed_values": sorted(values), "source": "用户核对当前游戏上下限／步长或完整档位"}


def fingerprint(plan: dict) -> str:
    content = {k: v for k, v in plan.items() if k != "fingerprint"}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def numeric_plan(meta: dict, rule: dict, domain: dict, baseline: str, fuel: float,
                 current_confirmed: bool, baseline_passed: bool) -> dict:
    name = rule["parameter"]
    if not rule["sign"] or name not in UNITS:
        raise ValueError("问题还不够具体。先区分高速推头、车尾不稳或触底，再生成数值方案。")
    if not current_confirmed or not baseline_passed or not baseline.strip():
        raise ValueError("需核对当前值与版本，并确认具名原基准在本次燃油下已 Passed Tech。")
    if not math.isfinite(fuel) or fuel < 0:
        raise ValueError("请填写当前用于 Tech 检查的燃油量。")
    if meta.get("fuel_capacity_l") and fuel > meta["fuel_capacity_l"]:
        raise ValueError("燃油量超过记录中的油箱容量。")
    if any(domain.get(k) != meta.get(k) for k in ("car", "track_id", "track", "build")) or domain.get("unit") != UNITS[name]:
        raise ValueError("档位记录不属于当前车型、布局、游戏版本或单位，请重新核对。")
    original = parameter_number(meta.get("setup_flat", {}).get(rule["path"]), name)
    target = next_value(original, rule["sign"], domain, meta["build"])
    if target is None:
        raise ValueError("当前值缺失、单位不符、不在合法档位中，或已到调整方向的边界。不能再往该方向改。")
    plan = {"schema": 1, "car": meta["car"], "track_id": meta["track_id"], "track": meta["track"], "build": meta["build"],
            "parameter": name, "parameter_path": rule["path"], "current": original, "target": target,
            "delta": target - original, "steps": 1, "sign": rule["sign"], "unit": UNITS[name],
            "baseline_name": baseline.strip(), "fuel_l": fuel, "baseline_tech": "用户确认 Passed Tech",
            "domain": domain, "other_parameters": "保持基准值；任何额外调整都需要新方案和重新 Tech 检查",
            "context_source": meta.get("context_source", "用户核对 IBT 快照仍对应当前车库"),
            "rollback": f"{name} 恢复 {original:g} {UNITS[name]}，或重新加载 {baseline.strip()}"}
    plan["fingerprint"] = fingerprint(plan)
    return plan


def validate_plan(plan: dict):
    if not plan or plan.get("fingerprint") != fingerprint(plan):
        raise ValueError("数值方案缺失或已发生变化，需重新生成。")
    domain = plan.get("domain", {})
    if (any(domain.get(k) != plan.get(k) for k in ("car", "track_id", "track", "build"))
            or plan.get("unit") != UNITS.get(plan.get("parameter"))
            or domain.get("unit") != plan.get("unit")
            or next_value(plan.get("current"), plan.get("sign", 0), domain, plan.get("build", "unknown")) != plan.get("target")):
        raise ValueError("目标不是当前上下文中的合法相邻档位。")


def tech_passed(plan: dict | None, report: dict | None) -> bool:
    if not plan or not report:
        return False
    try:
        validate_plan(plan)
    except (ValueError, TypeError):
        return False
    return bool(report.get("result") == "Passed Tech" and report.get("plan_fingerprint") == plan["fingerprint"]
                and report.get("same_setup_context") is True
                and report.get("observed_target") == plan["target"])


def tech_report(plan: dict, result: str, actual_value: str, confirmed: bool, note: str) -> dict:
    validate_plan(plan)
    if result not in {"Passed Tech", "Failed Tech"}:
        raise ValueError("请先在游戏里执行检查，再填写实际结果。")
    observed = parameter_number(actual_value, plan["parameter"])
    if result == "Passed Tech" and (not confirmed or observed != plan["target"]):
        raise ValueError("实际输入值必须等于本方案目标，且整套设置、车辆、布局、版本及燃油与检查一致。")
    if result == "Failed Tech" and not note.strip():
        raise ValueError("请记录游戏标红的项目或失败说明。")
    return {"result": result, "observed_target": observed, "same_setup_context": confirmed,
            "plan_fingerprint": plan["fingerprint"], "note": note.strip(), "source": "用户在游戏内查看并回填；助手未自动读取 Tech 结果"}
