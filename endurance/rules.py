"""Explainable, versioned experiments. No learned optimal-setup claims."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from endurance.paths import ROOT
from endurance.knowledge import interactions, parameter_info


def load_rules(path: Path | None = None) -> dict:
    return json.loads((path or ROOT / "config" / "setup_rules.json").read_text(encoding="utf-8"))


def supported(meta: dict) -> tuple[bool, str]:
    if meta.get("car") != "ferrari296gt3":
        return False, "首版只提供 Ferrari 296 GT3 调教规则；本记录仍可用于数据浏览。"
    if meta.get("track") != "nurburgring combinedshortb" or str(meta.get("track_id")) != "262":
        return False, "该布局尚未纳入首版调教验收；可以浏览遥测，不套用纽北耐力赛规则。"
    if meta.get("context_source") == "手动说明":
        if not meta.get("manual_dry_adjustable"):
            return False, "先确认本次为干地、干胎并允许调整设置；无需导入遥测。"
        return True, "依据你的手动说明；没有把它当作遥测观测。"
    tire = str(meta.get("setup_flat", {}).get("TiresAero.TireType.TireType", "")).lower()
    if meta.get("source_kind") in {"setup_html", "assistant_snapshot"}:
        if meta.get("planned_conditions") != "dry" or tire not in {'', 'dry'}:
            return False, "当前文件不适用于首版干地计划；不据此生成湿地调教。"
        return True, "按所选布局的干地计划分析文件基准；没有把计划条件当作实际路面观测。"
    if tire != "dry":
        return False, "干地轮胎状态未确认，首版不生成湿地调教实验。"
    wetness = meta.get("observed_wetness", [])
    if not wetness or any(w != 1 for w in wetness):
        return False, "本记录含非干燥路面或路面湿度未知；首版不据此推荐干地调教。"
    if str(meta.get("weekend_options", {}).get("IsFixedSetup", "unknown")).lower() in {"true", "1"}:
        return False, "该记录来自 Fixed Setup 会话。请在允许修改设置的练习／赛事会话中测试。"
    return True, "首版车型／布局匹配；条件和设置仍需按本次试跑核实。"


def next_value(current: float | None, sign: int, constraint: dict | None, build: str) -> float | None:
    """Use a user-verified enumerated domain only for the exact game build."""
    if current is None or not sign or not constraint or not constraint.get("verified"):
        return None
    if not build or build == "unknown" or constraint.get("build") != build:
        return None
    allowed = constraint.get("allowed_values", [])
    if not allowed or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in allowed):
        return None
    allowed = sorted(set(float(v) for v in allowed))
    matches = [i for i, v in enumerate(allowed) if math.isclose(current, v, abs_tol=1e-6)]
    if len(matches) != 1:
        return None
    i = matches[0] + sign
    return allowed[i] if 0 <= i < len(allowed) else None


def parameter_number(value, parameter: str) -> float | None:
    """Reject unexpected units rather than treating mm or radians as degrees."""
    unit = {"Front ARB blades": ("degrees", "deg", "°"), "Rear Wing Angle": ("degrees", "deg", "°"),
            "Front Total Toe-In": ("mm",), "Traction Control": ("",)}.get(parameter)
    text = str(value)
    if parameter == "Traction Control":
        text = re.sub(r"\s*\(TC(?:1\+TC2)?\)\s*$", "", text)
    match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*([^\d]*)\s*", text)
    if not match or unit is None or (match[2].strip() and match[2].strip().lower() not in unit):
        return None
    return float(match[1])


def trial_guide(config: dict, rule: dict, corner: str) -> dict:
    guide = config["trial_guides"][rule["trial_guide"]]
    protocol = config["trial_protocol"]
    return {
        **guide, "reported_corner": corner.strip(), "steps": protocol["steps"],
        "sources": [[f"Ferrari 296 GT3 官方手册第 {page} 页", f"{config['source']}#page={page}"]
                    for page in guide["manual_pages"]] + protocol["sources"],
    }


def recommend(meta: dict, symptom: str, feeling: str, corner: str,
              constraints: dict | None = None, facts: list[str] | None = None, mode: str = "感觉 + 数据") -> dict:
    config = load_rules()
    ok, reason = supported(meta)
    if not ok:
        return {"available": False, "reason": reason}
    if mode == "凭数据" and not facts:
        return {"available": False, "reason": "数据模式需要可用观测。也可以切换到凭感觉，独立创建实验。"}
    rule = next((r for r in config["rules"] if symptom in r["symptoms"]), None)
    if rule is None:
        return {"available": False, "reason": "请选择需要验证的驾驶感受。"}
    current = meta.get("setup_flat", {}).get(rule["path"])
    constraint = (constraints or {}).get(rule["parameter"])
    if constraint and constraint.get("car") != meta["car"]:
        constraint = None
    target = next_value(parameter_number(current, rule["parameter"]), rule["sign"], constraint, meta["build"])
    return {
        "available": True, "rule_id": rule["id"], "symptom": symptom, "feeling": feeling,
        "corner": corner, "parameter": rule["parameter"], "parameter_path": rule["path"],
        "current": current if current is not None and current != "" else "未知，请在游戏车库核对", "target": target,
        "direction": rule["direction"], "risk": rule["risk"], "verification": rule["verify"],
        "facts": ([] if mode == "凭感觉" else facts) or ["尚无用于此建议的数据观测。"],
        "subjective": feeling, "mode": mode, "context_source": meta.get("context_source", "IBT 快照"),
        "hypothesis": "车辆平衡是待验证的可能原因；路线、驾驶输入或轮胎状态也可能造成相似表现。",
        "mechanism": rule["mechanism"], "source": config["source"], "source_page": rule["source_page"],
        "source_note": config["source_note"], "build": meta["build"],
        "status": "待试跑", "numeric_note": "已核实本版本可选值" if target is not None else "未给数值：可选档位未核实，或当前值已到边界。",
        "parameter_knowledge": parameter_info(rule["parameter"]), "interactions": interactions(rule["parameter"]),
        "trial_guide": trial_guide(config, rule, corner),
        "certainty": "手册支持参数作用方向；本次问题的原因及改善效果尚未验证。",
    }


def setup_difference(before: dict, after: dict) -> list[dict]:
    # Show all snapshot differences including fuel/temperatures, explicitly labelled.
    a, b = before.get("setup_flat", {}), after.get("setup_flat", {})
    return [{"参数路径": key, "调整前": str(a.get(key, "缺失")), "调整后": str(b.get(key, "缺失"))}
            for key in sorted(set(a) | set(b)) if a.get(key) != b.get(key)]
