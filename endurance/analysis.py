"""Conservative lap quality, distance comparisons, and endurance evidence.

Metrics are observations, not inferred tire forces or causality. Errors remain in
the denominator for stability summaries even when excluded from pace statistics.
"""
from __future__ import annotations

from collections import defaultdict
import json
import math

import numpy as np
import polars as pl

from endurance.paths import ROOT


def values(df: pl.DataFrame, name: str, default=np.nan) -> np.ndarray:
    return df[name].to_numpy().astype(float) if name in df.columns else np.full(df.height, default)


def finite_median(arr) -> float | None:
    arr = np.asarray(arr, dtype=float)
    finite = arr[np.isfinite(arr)]
    return float(np.median(finite)) if len(finite) else None


def correction_count(df: pl.DataFrame) -> int | None:
    """Direction changes at 10 Hz after a 0.3 s average; not a spin detector."""
    if "steering_deg" not in df.columns or df.height < 30:
        return None
    t, angle = values(df, "time_s"), values(df, "steering_deg")
    if not np.isfinite(angle).all() or np.any(np.diff(t) <= 0):
        return None
    grid = np.arange(t[0], t[-1], .1)
    if len(grid) < 5:
        return 0
    smooth = np.convolve(np.interp(grid, t, angle), np.ones(3) / 3, mode="valid")
    delta = np.diff(smooth)
    signs = np.sign(delta[np.abs(delta) >= 2.0])
    return int(np.count_nonzero(signs[1:] != signs[:-1]))


def extract_laps(df: pl.DataFrame, meta: dict) -> tuple[pl.DataFrame, list[dict]]:
    t, pct, number = (values(df, k) for k in ("time_s", "lap_dist_pct", "lap_number"))
    session = values(df, "session_num", 0)
    pit, fuel = values(df, "on_pit_road", 0), values(df, "fuel_l")
    dt = np.diff(t)
    gap_limit = max(.25, 5 / meta["tick_rate"])
    run_break = np.r_[True, (dt <= 0) | (dt > gap_limit) | (np.diff(session) != 0) |
                      ((pit[:-1] > .5) & (pit[1:] < .5)) | (np.diff(fuel) > 1)]
    run_ids = np.cumsum(run_break).astype(int)
    lap_break = np.r_[True, (np.diff(number) != 0) | (np.diff(session) != 0) |
                      (np.diff(pct) < -.5) | (dt <= 0)]
    starts = np.flatnonzero(lap_break)
    stops = np.r_[starts[1:], len(t)]
    lap_ids = np.empty(len(t), dtype=int)
    laps = []
    for lap_id, (a, b) in enumerate(zip(starts, stops)):
        lap_ids[a:b] = lap_id
        part = df.slice(int(a), int(b - a))
        p = pct[a:b]
        begin = (a > 0 and pct[a - 1] > .99 and p[0] < .01 and session[a - 1] == session[a]
                 and 0 < t[a] - t[a - 1] <= gap_limit) or (a == 0 and p[0] <= 1e-5)
        finish = (b < len(t) and p[-1] > .99 and pct[b] < .01 and session[b] == session[a]
                  and 0 < t[b] - t[b - 1] <= gap_limit)
        full = bool(begin and finish)
        discontinuity = bool(np.any((np.diff(t[a:b]) <= 0) | (np.diff(t[a:b]) > gap_limit)))
        # Reject teleports, reversing, unphysical position jumps, or a changed run.
        discontinuity |= bool(np.any(np.diff(p) < -.001) or np.any(np.diff(p) > .02) or run_ids[a] != run_ids[b - 1])
        in_pits = bool(np.any(values(part, "on_pit_road", 0) > .5))
        surface = values(part, "track_surface")
        offtrack = bool(np.any(surface == 0))
        inc = values(part, "incidents")
        previous = values(df.slice(max(0, int(a) - 1), 1), "incidents")[0]
        incident_delta = int(max(0, np.nanmax(inc) - previous)) if np.isfinite(inc).all() and np.isfinite(previous) else None
        # Negative surface values indicate outside the world, not clean track.
        quality_known = all(c in part.columns and np.isfinite(values(part, c)).all()
                            for c in ("on_pit_road", "track_surface", "incidents"))
        outside = bool(np.any(surface < 0))
        reasons = []
        for condition, reason in ((not full, "非完整圈"), (discontinuity, "数据断续／位置跳变"),
                                 (in_pits, "进出维修区"), (offtrack, "冲出赛道"),
                                 ((incident_delta or 0) > 0, "事故计数增加"), (outside, "车辆不在赛道世界内"),
                                 (not quality_known, "缺少有效圈核验通道")):
            if condition:
                reasons.append(reason)
        duration = float(t[b] - t[a]) if finish else float(t[b - 1] - t[a])
        row = {
            "lap_id": lap_id, "lap_number": int(number[a]), "session_num": int(session[a]),
            "run_id": int(run_ids[a]), "sample_start": int(a), "sample_stop": int(b),
            "start_s": float(t[a]), "duration_s": duration,
            "complete": full, "valid": not reasons, "reasons": reasons,
            "offtrack": offtrack, "incident_delta": incident_delta,
            "quality_known": quality_known, "discontinuity": discontinuity,
            "fuel_start_l": float(fuel[a]) if np.isfinite(fuel[a]) else None,
            "fuel_end_l": float(fuel[b - 1]) if np.isfinite(fuel[b - 1]) else None,
            "steering_changes": correction_count(part),
        }
        for c in ("track_temp_c", "air_temp_c", "wetness", "tire_compound", "weight_penalty_kg", "power_adjust"):
            row[c] = finite_median(values(part, c))
        row["in_car_changes"] = [c for c in ("dcBrakeBias", "dcTractionControl", "dcABS")
                                  if c in part.columns and part[c].n_unique() > 1]
        laps.append(row)
    return df.with_columns(pl.Series("lap_id", lap_ids), pl.Series("run_id", run_ids)), laps


def lap_frame(df: pl.DataFrame, lap_id: int) -> pl.DataFrame:
    return df.filter(pl.col("lap_id") == lap_id)


def pace_summary(laps: list[dict]) -> dict:
    valid = [l for l in laps if l["valid"]]
    times = [l["duration_s"] for l in valid]
    # Includes incomplete/incident laps rather than silently dropping mistakes.
    errors = sum(bool(l["offtrack"] or (l["incident_delta"] or 0) > 0) for l in laps)
    known = sum(l["quality_known"] for l in laps)
    return {
        "total": len(laps), "valid": len(valid), "errors": errors,
        "unknown_quality": len(laps) - known,
        "median_s": finite_median(times),
        "iqr_s": float(np.percentile(times, 75) - np.percentile(times, 25)) if times else None,
        "error_rate": sum(bool(l["offtrack"] or (l["incident_delta"] or 0) > 0) for l in laps if l["quality_known"]) / known if known else None,
        "steering_changes_median": finite_median([l["steering_changes"] for l in valid if l["steering_changes"] is not None]),
    }


def compatibility(a: dict, b: dict) -> list[str]:
    blockers = []
    for key, title in (("car", "车型"), ("track_id", "布局 ID"), ("track", "赛道路径"),
                       ("build", "游戏版本"), ("driver_id", "驾驶员")):
        if not a.get(key) or not b.get(key) or "unknown" in (a[key], b[key]):
            blockers.append(f"{title}未知")
        elif a[key] != b[key]:
            blockers.append(f"{title}不同")
    if abs((a.get("track_length_m") or 0) - (b.get("track_length_m") or 0)) > 5:
        blockers.append("赛道长度不同")
    if a.get("track_version") != b.get("track_version"):
        blockers.append("赛道版本不同")
    return blockers


def condition_key(lap: dict) -> tuple | None:
    """Explicit conservative bins; never fill missing conditions with zeros."""
    needed = ("fuel_start_l", "track_temp_c", "air_temp_c", "wetness", "tire_compound", "weight_penalty_kg", "power_adjust")
    if any(lap.get(k) is None or not math.isfinite(lap[k]) for k in needed):
        return None
    return (int(lap["fuel_start_l"] // 10), int(lap["track_temp_c"] // 3),
            int(lap["air_temp_c"] // 3), int(lap["wetness"]), int(lap["tire_compound"]),
            round(lap["weight_penalty_kg"], 2), round(lap["power_adjust"], 4))


def compare_runs(before_meta: dict, after_meta: dict, before: list[dict], after: list[dict],
                 setup_confirmed: bool = False, conditions_confirmed: bool = False) -> dict:
    blockers = compatibility(before_meta, after_meta)
    a, b = pace_summary(before), pace_summary(after)
    result = {"status": "证据不足", "blockers": blockers, "before": a, "after": b, "groups": [],
              "delta_s": None, "conclusion": "没有足够的同条件有效圈，不判断调教效果。",
              "limits": "观察到的差异不是因果证明；短试跑不代表三小时耐力赛已验证。"}
    if blockers:
        return result
    if not setup_confirmed:
        blockers.append("尚未确认两组各自使用一致设置，且仅改变计划中的变量")
    if not conditions_confirmed:
        blockers.append("轮胎使用阶段、交通、路面状态等未核实")
    if any(l.get("in_car_changes") for l in before + after):
        blockers.append("存在圈内 Brake Bias／TC／ABS 变化，请另选设置一致的驾驶段")
    groups_a, groups_b = defaultdict(list), defaultdict(list)
    for rows, dest in ((before, groups_a), (after, groups_b)):
        for lap in rows:
            k = condition_key(lap)
            if lap["valid"] and k is not None:
                dest[k].append(lap)
    deltas = []
    for key in sorted(set(groups_a) | set(groups_b)):
        aa, bb = groups_a[key], groups_b[key]
        enough = len(aa) >= 3 and len(bb) >= 3
        group = {"fuel_l": f"{key[0] * 10}–{key[0] * 10 + 10}",
                 "track_temp_c": f"{key[1] * 3}–{key[1] * 3 + 3}",
                 "air_temp_c": f"{key[2] * 3}–{key[2] * 3 + 3}",
                 "wetness": key[3], "tire_compound": key[4], "weight_penalty_kg": key[5],
                 "power_adjust": key[6], "before_n": len(aa), "after_n": len(bb), "eligible": enough,
                 "delta_s": None}
        if enough:
            sa, sb = pace_summary(aa), pace_summary(bb)
            delta = sb["median_s"] - sa["median_s"]
            threshold = max(.2, sa["median_s"] * .001, (sa["iqr_s"] + sb["iqr_s"]) / 2)
            group.update(delta_s=delta, threshold_s=threshold)
            deltas.append((delta, threshold))
        result["groups"].append(group)
    if not deltas:
        blockers.append("每个可比条件组需调整前后各至少三圈有效圈")
    if a["unknown_quality"] or b["unknown_quality"]:
        blockers.append("部分圈缺少稳定性核验通道")
    if blockers:
        return result
    result["delta_s"] = finite_median([d for d, _ in deltas])
    stability_worse = b["error_rate"] > a["error_rate"]
    if stability_worse:
        result.update(status="初步恶化", conclusion="调整后失误圈占比上升，不推荐因最快圈更快而保留此设置。")
    elif all(d < -threshold for d, threshold in deltas):
        result.update(status="初步改善", conclusion="各可比组代表性圈速改善超过观察波动，且记录内失误占比未上升；还需核对手感及长段表现。")
    elif all(d > threshold for d, threshold in deltas):
        result.update(status="初步恶化", conclusion="各可比组代表性圈速变慢超过观察波动，建议回看基准设置。")
    else:
        result["conclusion"] = "差异未稳定超过观察波动，或不同条件组方向不一致，暂不判断改善。"
    return result


def distance_trace(df: pl.DataFrame, start: float, end: float, points: int = 400) -> dict:
    if df.height < 2 or end <= start:
        raise ValueError("距离范围或样本无效。")
    x = values(df, "distance_m")
    t = values(df, "time_s")
    if not np.isfinite(x).all() or not np.isfinite(t).all():
        raise ValueError("距离或时间缺失，不能进行距离插值。")
    dt = np.diff(t)
    if np.any(np.diff(x) < -.5) or np.any(dt <= 0):
        raise ValueError("这一段存在倒车／数据跳变，不能进行距离插值。")
    if np.any(dt > max(.25, 5 * np.median(dt))) or np.any(np.diff(x) > np.maximum(100, dt * 150)):
        raise ValueError("这一段存在采样中断／位置跳变，不能跨缺口插值。")
    x, index = np.unique(x, return_index=True)
    lo, hi = max(start, x[0]), min(end, x[-1])
    if hi <= lo or lo - start > 5 or end - hi > 5:
        raise ValueError("圈数据未覆盖所选距离范围，不能外推补齐。")
    grid = np.linspace(lo, hi, points)
    out = {"distance_m": grid}
    for channel in ("time_s", "speed_kph", "throttle", "brake", "steering_deg", "lat_g", "yaw_rate_deg_s"):
        if channel in df.columns:
            y = values(df, channel)[index]
            if np.isfinite(y).all():
                out[channel] = np.interp(grid, x, y)
    out["elapsed_s"] = out["time_s"] - out["time_s"][0]
    return out


def compare_corner(user: pl.DataFrame, ref: pl.DataFrame | None, corner: dict) -> dict:
    start, apex, end = [float(corner[k]) for k in ("start_m", "apex_m", "end_m")]
    mid_start, mid_end = float(corner["mid_start_m"]), float(corner["mid_end_m"])
    u = distance_trace(user, start, end)
    result = {"facts": [], "phases": [], "trace": u, "reference": None,
              "hypotheses": ["方向、速度或油门差异可能来自路线、输入、轮胎状态或车辆平衡，不能单独确定原因。"]}
    result["facts"].append(f"本圈该段最低速度 {np.min(u['speed_kph']):.1f} km/h。")
    if "steering_deg" in u:
        result["facts"].append(f"该段方向盘绝对角度中位数 {np.median(np.abs(u['steering_deg'])):.1f}°；不是前轮转角。")
    if ref is None:
        result["facts"].append("未选择参考圈：不估计损失时间或最优刹车点。")
        return result
    # Same grid extent for both recordings, no endpoint extrapolation.
    lo = max(start, user["distance_m"].min(), ref["distance_m"].min())
    hi = min(end, user["distance_m"].max(), ref["distance_m"].max())
    u, r = distance_trace(user, lo, hi), distance_trace(ref, lo, hi)
    result.update(trace=u, reference=r)
    for name, a, b in (("刹车／入弯", lo, mid_start), ("弯中", mid_start, mid_end), ("出弯", mid_end, hi)):
        if a < b and lo <= a <= b <= hi:
            ut = np.interp([a, b], u["distance_m"], u["time_s"])
            rt = np.interp([a, b], r["distance_m"], r["time_s"])
            result["phases"].append({"阶段": name, "本圈秒": float(ut[1] - ut[0]),
                                     "参考秒": float(rt[1] - rt[0]), "差值秒": float(np.diff(ut)[0] - np.diff(rt)[0])})
    for channel, threshold, text in (("brake", .05, "开始刹车"), ("throttle", .9, "出弯达到 90% 油门")):
        if channel in u and channel in r:
            def point(trace):
                mask = trace[channel] > threshold
                mask &= trace["distance_m"] >= apex if channel == "throttle" else trace["distance_m"] <= apex
                indices = np.flatnonzero(mask)
                return float(trace["distance_m"][indices[0]]) if len(indices) else None
            a, b = point(u), point(r)
            if a is not None and b is not None:
                result["facts"].append(f"{text}的位置比参考圈{'晚' if a > b else '早'} {abs(a - b):.1f} m（限所选分段）。")
    return result


def repeated_corner(df: pl.DataFrame, laps: list[dict], corner: dict) -> dict:
    """Describe repeated passes, retaining error laps and never inventing a target."""
    rows = []
    for lap in laps:
        try:
            trace = distance_trace(lap_frame(df, lap["lap_id"]), corner["start_m"], corner["end_m"])
        except ValueError:
            continue
        rows.append({"片段": lap["lap_id"], "游戏圈": lap["lap_number"],
                     "最低速度 km/h": round(float(np.min(trace["speed_kph"])), 1),
                     "本段用时 s": round(float(trace["elapsed_s"][-1]), 3),
                     "方向绝对值中位数 °": round(float(np.median(np.abs(trace["steering_deg"]))), 1) if "steering_deg" in trace else None,
                     "燃油 L": lap["fuel_start_l"], "赛道温度 °C": lap["track_temp_c"],
                     "整圈质量": "有效完整圈" if lap["valid"] else "、".join(lap["reasons"])})
    if len(rows) < 3:
        message = f"找到 {len(rows)} 次连续覆盖本段的记录；至少三次才能描述重复行为。"
    else:
        speeds = [r["最低速度 km/h"] for r in rows]
        message = f"找到 {len(rows)} 次连续通过本段：最低速度中位数 {np.median(speeds):.1f} km/h，范围 {min(speeds):.1f}–{max(speeds):.1f} km/h。这是观测分布，不是最优速度。"
    return {"rows": rows, "message": message}


def validate_corners(corners: list[dict], length: float) -> list[dict]:
    if not corners:
        raise ValueError("至少保存一个分段。")
    names = set()
    for c in corners:
        name = str(c.get("name", "")).strip()
        vals = [float(c[k]) for k in ("start_m", "mid_start_m", "apex_m", "mid_end_m", "end_m")]
        if not name or name in names or not all(math.isfinite(x) for x in vals):
            raise ValueError("分段名称必须唯一且非空，距离必须为有限数值。")
        if not 0 <= vals[0] < vals[1] <= vals[2] <= vals[3] < vals[4] <= length:
            raise ValueError(f"{name}：需要起点 < 弯中开始 ≤ 弯心 ≤ 弯中结束 < 终点，且位于本布局范围内。")
        names.add(name)
    return corners


def sector_segments(meta: dict) -> list[dict]:
    """Official split distances are verified by file metadata; phases are drafts."""
    length = meta["track_length_m"]
    starts = sorted(set(float(s["SectorStartPct"]) for s in meta.get("sectors", []) if 0 <= float(s["SectorStartPct"]) < 1))
    if not starts:
        starts = [0.0]
    return [{"name": f"官方分段 {i + 1}", "start_m": round(a * length, 1),
             "mid_start_m": round((a + (b - a) * .35) * length, 1),
             "apex_m": round((a + (b - a) * .5) * length, 1),
             "mid_end_m": round((a + (b - a) * .65) * length, 1),
             "end_m": round(b * length, 1), "verified": False}
            for i, (a, b) in enumerate(zip(starts, starts[1:] + [1.0]))]


def default_segments(meta: dict) -> tuple[list[dict], str]:
    config = json.loads((ROOT / "config" / "nurburgring_vln.json").read_text(encoding="utf-8"))
    generic = sector_segments(meta)
    if (meta["track_id"] == config["track_id"] and meta["track"] == config["track"]
            and abs(meta["track_length_m"] - config["track_length_m"]) < 2):
        return config["corners"] + generic, config["description"]
    return generic, "官方计时分段来源已核对，但其中弯心与阶段边界仍需人工校准。"


def endurance_coverage(laps: list[dict], capacity_l: float | None, stint_minutes: float) -> dict:
    good = [l for l in laps if l["valid"]]
    high = sum(l["fuel_start_l"] is not None and l["fuel_start_l"] >= .7 * capacity_l for l in good) if capacity_l else 0
    low = sum(l["fuel_start_l"] is not None and l["fuel_start_l"] <= .3 * capacity_l for l in good) if capacity_l else 0
    runs = defaultdict(list)
    for l in laps:
        runs[(l.get("recording_id", ""), l["run_id"])].append(l)
    longest = max((sum(l["duration_s"] for l in rows if not l.get("discontinuity")) for rows in runs.values()), default=0) / 60
    return {"high_fuel_laps": high, "low_fuel_laps": low, "longest_run_minutes": longest,
            "stint_duration_observed": longest >= stint_minutes,
            "message": "高低油量按油箱容量的 ≥70% / ≤30% 分组；有数据不等于通过耐久验证。" if capacity_l else "缺少油箱容量，高低油量覆盖待核实。"}
