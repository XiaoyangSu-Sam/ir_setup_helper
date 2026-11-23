"""Automatic evidence resolution: partial observed values are never a legal range."""
from __future__ import annotations

from copy import deepcopy
import json
import math

from endurance.adjustment import UNITS, fingerprint
from endurance.paths import ROOT
from endurance.rules import parameter_number, supported
from endurance.compatibility import source_review, parameter_review
from endurance.ibt import is_simulated


def same_context(a, b):
    return all(a.get(k) and a.get(k) != "unknown" and a.get(k) == b.get(k) for k in ("car", "track_id", "track", "build"))


def choose_setup(live, current, car, track):
    if live:
        if live["car"] == car and (live["track_id"], live["track"]) == track:
            return deepcopy(live), "live"
        return None, "游戏中的车辆或布局与侧栏不同，请选择实际使用的组合。"
    if current:
        result = deepcopy(current["meta"])
        result.update(source_kind="historical_ibt", context_source="历史 IBT 设置快照，不是当前车库")
        return result, "history"
    return None, "还没有读到设置。打开 iRacing 练习并加载车辆后点重新读取即可；不需要填写参数范围。"


def settings_fingerprint(meta):
    return fingerprint({k: meta.get(k) for k in ("car", "track_id", "track", "build", "setup_flat", "car_component_build")})


def automatic_plan(meta: dict, rule: dict, records: list[dict]) -> dict:
    p = rule["parameter"]
    base = {"ready": False, "parameter": p, "reason": "", "source_kind": meta.get("source_kind", "historical_ibt")}
    if is_simulated(meta):
        return {**base, "reason": "这是模拟遥测。请选择实际设置文件作为推荐基准。"}
    ok, reason = supported(meta)
    if not ok:
        return {**base, "reason": reason}
    if not rule["sign"] or p not in UNITS:
        return {**base, "reason": "需要先分清车头推还是车尾滑；工具不会为模糊问题随意选数值。"}
    raw_value = meta.get("setup_flat", {}).get(rule["path"])
    current = parameter_number(raw_value, p)
    if current is None or not math.isfinite(current):
        reason = f"工具尚未从文件中识别出 {p}；这是字段解析缺口，暂不生成数值建议。" if raw_value is None else f"已读到 {p} = {raw_value}，但工具尚不支持这个单位或数值格式，暂不生成数值建议。"
        return {**base, "reason": reason}
    if not meta.get("build") or meta["build"] == "unknown":
        return {**base, "reason": "工具尚未自动读到游戏版本，暂时不能匹配数值依据；无需填写版本或重新上传文件。"}
    cap = json.loads((ROOT / "config" / "automatic_policy.json").read_text(encoding="utf-8"))["max_change"][p]
    evidence = {}
    for record in records:
        m = record["meta"]
        if is_simulated(m):
            continue
        same = same_context(meta, m)
        review = None if same else source_review(meta, m, p)
        if not same and not review:
            continue
        v = parameter_number(m.get("setup_flat", {}).get(rule["path"]), p)
        if v is not None and 0 < (v - current) * rule["sign"] <= cap + 1e-8:
            item = {"record_id": record["id"], "source_name": m.get("source_name", "IBT"), "build": m["build"], 'value': v}
            if review:
                item.update(review_id=review['id'], compatibility_basis=review['basis'], limitation=review['limitation'], review_source=review['source'])
                item['matching_settings'] = {path: m['setup_flat'][path] for path in review.get('matching_settings', {}).get(p, [])}
            evidence.setdefault(v, []).append(item)
    if not evidence:
        return {**base, "reason": "暂时无法生成调整建议。你的文件已成功读取，请先保持当前设置。此问题需要软件更新解决，无需你操作。",
                'detail': f"工具没有找到 {meta['build']} 下该方向的同版本数值或经过兼容复核的候选值。", "current": current}
    # Prefer exact-build evidence when available, regardless of older candidates.
    exact = {v: [e for e in items if e['build'] == meta['build']] for v, items in evidence.items()}
    exact = {v: items for v, items in exact.items() if items}
    evidence = exact or evidence
    target = min(evidence, key=lambda v: abs(v - current))
    transferred = any(e.get('review_id') for e in evidence[target])
    flat = meta["setup_flat"]
    fuel = flat.get("Chassis.Rear.FuelLevel")
    checks = ["车型与布局匹配", "目标值来自经过参数兼容复核的历史记录（不是同版本实跑验证）" if transferred else "目标值在同版本同布局的本机记录中实际出现过", "改动未超过首轮实验幅度上限", "本轮只改变一个参数，未叠加车高或弹簧调整"]
    plan = {"schema": 2, "ready": True, "car": meta["car"], "track_id": meta["track_id"], "track": meta["track"], "build": meta["build"],
            "parameter": p, "parameter_path": rule["path"], "current": current, "target": target,
            "delta": target - current, "steps": None, "unit": UNITS[p], "sign": rule["sign"],
            "baseline_name": meta.get("source_name", "读取的设置快照"), "fuel_text": fuel or "读取的来源没有燃油字段",
            "source_kind": meta.get("source_kind", "historical_ibt"), "source_observed_at": meta.get("observed_at", meta.get("start_utc")),
            "baseline_setup": deepcopy(flat), "baseline_fingerprint": settings_fingerprint(meta),
            "evidence": evidence[target], "checks": checks, "max_change": cap,
            'parameter_evidence': 'reviewed_transfer' if transferred else 'same_build',
            'car_component_build': meta.get('car_component_build'), 'car_component_source': meta.get('car_component_source'),
            "domain_status": "部分已观测值；不是完整合法档位表", "tech_status": "未接通游戏检查结果",
            "build_source": meta.get('build_source', '来源文件中的版本'),
            "build_assumption": meta.get('build_assumption'), "build_detection": deepcopy(meta.get('build_detection')),
            "rollback": f"{p} 恢复 {current:g} {UNITS[p]}", "other_parameters": "保持读取的基准值"}
    plan["fingerprint"] = fingerprint(plan)
    return plan


def validate_automatic_plan(plan):
    if not plan or plan.get("schema") != 2 or plan.get("fingerprint") != fingerprint(plan):
        raise ValueError("自动方案缺失或已变更")
    if not plan.get('evidence'):
        raise ValueError('缺少目标值来源')
    for e in plan['evidence']:
        if not e.get('record_id') or ('value' in e and e['value'] != plan['target']):
            raise ValueError('目标值来源不一致')
        if e.get('build') != plan['build']:
            review = parameter_review(plan, e.get('build'), plan['parameter'])
            if not review or review['id'] != e.get('review_id') or plan.get('parameter_evidence') != 'reviewed_transfer':
                raise ValueError('跨版本参数来源未通过特定车型与车辆包的兼容复核')
            for path in review.get('matching_settings', {}).get(plan['parameter'], []):
                if plan.get('baseline_setup', {}).get(path) is None or e.get('matching_settings', {}).get(path) != plan['baseline_setup'][path]:
                    raise ValueError('参数的关联设置与来源不一致')
    cap = json.loads((ROOT / "config" / "automatic_policy.json").read_text(encoding="utf-8"))["max_change"].get(plan.get("parameter"))
    delta = plan["target"] - plan["current"]
    if cap is None or not all(math.isfinite(plan[k]) for k in ("current", "target", "max_change")) or plan["max_change"] != cap or plan["sign"] not in (-1, 1) or not 0 < delta * plan["sign"] <= cap + 1e-8 or plan.get("unit") != UNITS.get(plan.get("parameter")):
        raise ValueError("自动方案幅度或单位不符")
    if plan.get("tech_status") != "未接通游戏检查结果":
        raise ValueError("没有游戏检查结果适配器，不能声称已通过 Tech")


def observe_plan(plan, records):
    """A matching later snapshot is adoption evidence, NOT a Passed Tech verdict."""
    expected = dict(plan["baseline_setup"])
    key = plan["parameter_path"]
    for record in records:
        m = record["meta"]
        if not same_context(plan, m) or m.get("start_utc", "") <= plan.get("created_at", ""):
            continue
        if parameter_number(m.get("setup_flat", {}).get(key), plan["parameter"]) == plan["target"]:
            changed = [p for p in set(expected) | set(m["setup_flat"]) if p != key and expected.get(p) != m["setup_flat"].get(p)]
            return {"adopted": True, "record_id": record["id"], "other_differences": changed,
                    "message": "新记录中出现了目标值；其他快照变化仍需由分析器核对，不能据此认定 Passed Tech。"}
    return {"adopted": False, "message": "尚未发现采用目标值的新记录。游戏 Tech 结果未接通，无需填写确认表。"}
