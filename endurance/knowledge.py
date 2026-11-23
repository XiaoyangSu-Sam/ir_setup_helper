"""Documented mechanisms and user-attributed official examples, not learned optima."""
from __future__ import annotations

import json
import re

from endurance.paths import ROOT


def knowledge() -> dict:
    return json.loads((ROOT / "config" / "parameter_knowledge.json").read_text(encoding="utf-8"))


def parameter_info(name: str) -> dict | None:
    return next((p for p in knowledge()["parameters"] if p["name"] == name), None)


def interactions(name: str) -> list[dict]:
    param = parameter_info(name)
    return [c for c in knowledge()["couplings"] if param and c["group"] == param["group"]]


def suggest_symptoms(text: str) -> list[str]:
    """Explicit phrase hints only. The user confirms the interpretation in the UI."""
    sentences = re.split(r"[，。；！？,;!?\n]", text)
    hints = []
    for sentence in sentences:
        if any(neg in sentence for neg in ("不推头", "没有推头", "不甩尾", "没有甩尾", "不迟钝", "没有迟钝")):
            continue
        push = any(x in sentence for x in ("推头", "转不过", "不肯转", "不肯进弯"))
        loose = any(x in sentence for x in ("甩尾", "车尾滑", "车尾一直滑", "车尾不稳", "屁股滑", "屁股就滑"))
        if "高速" in sentence and push:
            hints.append("高速推头")
        elif "高速" in sentence and loose:
            hints.append("高速车尾不稳")
        elif any(x in sentence for x in ("出弯", "给油", "加油")) and loose:
            hints.append("出弯不稳")
        elif push and any(x in sentence for x in ('入弯', '进弯', '拖刹')):
            hints.append('入弯推头')
        elif push:
            hints.append("弯中推头")
        elif any(x in sentence for x in ("入弯迟钝", "转向慢", "车头迟钝")):
            hints.append("入弯迟钝")
    return list(dict.fromkeys(hints))


def manual_context(car: str, track_id: str, track: str, build: str,
                   dry_adjustable: bool, setup_flat: dict | None = None) -> dict:
    return {"car": car, "track_id": track_id, "track": track, "build": build.strip() or "unknown",
            "context_source": "手动说明", "manual_dry_adjustable": dry_adjustable,
            "setup_flat": setup_flat or {}}


def initial_baseline(car: str, track: str) -> list[str]:
    if car != "ferrari296gt3":
        return ["该车型尚无已核对的初始方案，请先使用其官方适用基准。"]
    return ["先找与当前布局匹配的官方 endurance 设置；纽北含 Nordschleife 的布局还要核对专用设置及车高规则。",
            "如果没有对应条目，先用能通过当前 Tech 检查的官方基准；本页不假定游戏里存在某个具体文件。",
            "先保留基准的完整搭配，按预计单段燃油测试；仅凭比赛总时长不能决定燃油或轮胎使用时长。",
            "还没发现具体问题时先建立手感基线：入弯响应、弯中转向、出弯可控性和高速信心。"]


def official_example(name: str, car: str, track_id: str, track: str, build: str,
                     setup_flat: dict, source_note: str, confirmed: bool, record_id: str | None = None) -> dict:
    if not confirmed or not name.strip() or not source_note.strip() or not build.strip() or build == "unknown":
        raise ValueError("需要官方配置名称、实际游戏版本、来源说明，以及未改动官方配置的核对声明。")
    if car != "ferrari296gt3" or not setup_flat:
        raise ValueError("需要 Ferrari 296 GT3 的实际参数；不能保存空白配置实例。")
    allowed = {p["path"] for p in knowledge()["parameters"]}
    clean = {k: str(v).strip() for k, v in setup_flat.items() if k in allowed and str(v).strip()}
    if not clean:
        raise ValueError("没有可识别的参数值。")
    return {"name": name.strip(), "car": car, "track_id": track_id, "track": track, "build": build.strip(),
            "setup": {}, "setup_flat": clean, "record_id": record_id, "kind": "official_example",
            "source_note": source_note.strip(), "source_verification": "用户核对为未改动的官方设置；助手未独立鉴定",
            "locally_validated": False, "validation_level": "官方实例／个人适配未验证", "parent_id": None}


def compare_examples(a: dict, b: dict) -> dict:
    mismatches = [k for k in ("car", "track_id", "track", "build") if a.get(k) != b.get(k) or not a.get(k) or a.get(k) == "unknown"]
    if mismatches:
        return {"rows": [], "groups": [], "message": "车型、布局或游戏版本不同／未知，不能作为同条件搭配对照。"}
    rows, groups = [], set()
    for p in knowledge()["parameters"]:
        av, bv = a["setup_flat"].get(p["path"]), b["setup_flat"].get(p["path"])
        if av is not None and bv is not None and av != bv:
            rows.append({"参数": p["name"], "实例 A": av, "实例 B": bv})
            groups.add(p["group"])
    return {"rows": rows, "groups": sorted(groups),
            "message": "只显示双方都记录过的参数差异；共同变化是实例事实，不证明搭配更快，也不证明变化互为因果。"}
