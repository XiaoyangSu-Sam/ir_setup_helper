"""The assistant's portable setup format. Game-native saves belong to Garage."""

import json
import math
from pathlib import Path

from endurance.adjustment import fingerprint
from endurance.automatic import validate_automatic_plan
from endurance.rules import load_rules, parameter_number

FORMAT = "endurance-lab.setup"
MAX_BYTES = 2_000_000


def _fields(meta, name, settings):
    return {
        "format": FORMAT, "schema": 1, "name": name,
        **{key: meta[key] for key in ("car", "track_id", "track", "build")},
        "setup_flat": settings,
        "planned_conditions": _conditions(meta),
    }


def _conditions(meta):
    observed = meta.get("observed_wetness", [])
    return "dry" if observed == [1] or meta.get("planned_conditions") == "dry" else None


def _encode(document):
    document["fingerprint"] = fingerprint(document)
    payload = json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise ValueError("设置快照超过 2 MB，无法导出为可重新导入的文件。")
    return payload


def export_snapshot(version):
    """Export settings only, with contextual metadata and a portable checksum."""
    meta = {**version, **(version.get("meta") or {})}
    name = (version.get("name") or "设置快照").removesuffix(".json")
    document = _fields(meta, name, version["setup_flat"])
    if meta.get("adjustment"):
        document["adjustment"] = meta["adjustment"]
    if meta.get("origin"):
        document["origin"] = meta["origin"]
    return _encode(document)


def export_candidate(meta, plan):
    validate_automatic_plan(plan)
    settings = plan["baseline_setup"]
    if settings != meta.get("setup_flat") or any(plan[key] != meta.get(key) for key in ("car", "track_id", "track", "build")):
        raise ValueError("方案与当前基准不一致，请重新生成方案。")
    parameter, path = plan["parameter"], plan["parameter_path"]
    if parameter_number(settings.get(path), parameter) != plan["current"]:
        raise ValueError("方案原值与基准不一致。")
    suffix = {"deg": " degrees", "mm": " mm", "档": " (TC)"}[plan["unit"]]
    target = f"{plan['target']:g}{suffix}"
    if parameter_number(target, parameter) != plan["target"]:
        raise ValueError("目标值无法无损写入文件。")
    document = _fields(meta, f"{plan['baseline_name']} · 试调候选", {**settings, path: target})
    document["adjustment"] = {"baseline": plan["baseline_name"], "parameter": parameter, "path": path,
                              "before": settings[path], "after": target}
    document["origin"] = {"source": plan["baseline_name"], "sha256": meta.get("file_hash"),
                          "target_evidence_build": plan["evidence"][0]["build"]}
    return _encode(document)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("设置文件有重复字段。")
        result[key] = value
    return result


def _scalar(value):
    return value is None or type(value) in (str, bool, int) or (type(value) is float and math.isfinite(value))


def parse_snapshot(payload, filename, car, track_id, track):
    if not payload or len(payload) > MAX_BYTES:
        raise ValueError("设置快照为空或超过 2 MB。")
    try:
        data = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("无法读取这个设置快照，文件可能损坏。") from exc
    if not isinstance(data, dict):
        raise ValueError("请选择助手导出的设置快照 JSON。")
    if "format" in data:
        if data["format"] != FORMAT or type(data.get("schema")) is not int or data["schema"] != 1:
            raise ValueError("不支持这个设置快照格式或版本。")
        try:
            valid_checksum = data.get("fingerprint") == fingerprint(data)
        except (ValueError, UnicodeError, RecursionError):
            valid_checksum = False
        if not valid_checksum:
            raise ValueError("设置快照校验失败，请重新下载原文件。")
    elif not {"name", "build", "validation_level"}.issubset(data):
        raise ValueError("请选择助手导出的设置快照 JSON。")
    if (data.get("car"), str(data.get("track_id")), data.get("track")) != (car, track_id, track):
        raise ValueError("设置快照的车型或布局与当前选择不同。")
    build, settings = data.get("build"), data.get("setup_flat")
    if not isinstance(build, str) or not build.strip() or len(build) > 128 or not isinstance(settings, dict) or not settings:
        raise ValueError("设置快照缺少版本或参数。")
    if any(not key.strip() or not (_scalar(value) or isinstance(value, list) and all(_scalar(v) for v in value))
           for key, value in settings.items()):
        raise ValueError("设置快照含无法读取的参数值。")
    adjustment = data.get("adjustment") if data.get("format") == FORMAT else None
    if adjustment is not None:
        valid_adjustment = isinstance(adjustment, dict) and all(
            isinstance(adjustment.get(k), str) for k in ("baseline", "parameter", "path", "before", "after")
        )
        if not valid_adjustment or not any(
            r["parameter"] == adjustment["parameter"] and r["path"] == adjustment["path"] for r in load_rules()["rules"]
        ) or settings.get(adjustment["path"]) != adjustment["after"]:
            raise ValueError("设置快照的调整说明与参数不一致。")
    original_meta = data.get("meta") if "format" not in data and isinstance(data.get("meta"), dict) else {}
    conditions = data.get("planned_conditions") if data.get("format") == FORMAT else _conditions(original_meta)
    origin = data.get("origin") if data.get("format") == FORMAT else None
    if origin is not None and (not isinstance(origin, dict) or not all(isinstance(v, str) or v is None for v in origin.values())):
        raise ValueError("设置快照的来源字段有误。")
    return {
        "car": car, "track_id": track_id, "track": track, "build": build, "setup_flat": settings,
        "source_kind": "assistant_snapshot", "source_name": Path(filename).name,
        "context_source": "助手设置快照", "setup_scope": "助手可重新导入的参数快照",
        "track_context": "快照注明车型和布局", "planned_conditions": "dry" if conditions == "dry" else None,
        "observed_wetness": [], "adjustment": adjustment, "origin": origin,
    }
