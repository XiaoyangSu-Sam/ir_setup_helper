"""Telemetry calculations for the setup A/B timing wall."""
from dataclasses import dataclass
from datetime import datetime
import math
from zoneinfo import ZoneInfo

import numpy as np

from endurance.analysis import compatibility, condition_key
from endurance.ibt import is_simulated


def common_conditions(before, after):
    """Group comparable valid laps without pooling different fuel or weather bins."""
    def collect(laps):
        groups = {}
        seen = set()
        for lap in laps:
            identity = (lap["recording_id"], lap["lap_id"])
            if identity in seen or not lap["valid"] or lap.get("in_car_changes"):
                continue
            seen.add(identity)
            if (key := condition_key(lap)) is not None:
                groups.setdefault(key, []).append(lap)
        return groups

    a, b = collect(before), collect(after)
    return {key: (a[key], b[key]) for key in sorted(a.keys() & b.keys(),
             key=lambda k: (-min(len(a[k]), len(b[k])), k))}


def timing_boundaries(meta):
    length = meta.get("track_length_m")
    if not length or not math.isfinite(length) or length <= 0:
        raise ValueError("缺少可靠赛道长度。")
    starts = {0.0}
    for sector in meta.get("sectors", []):
        try:
            fraction = float(sector["SectorStartPct"])
        except (ValueError, TypeError, KeyError):
            raise ValueError("遥测计时线数据无法读取。") from None
        if not 0 <= fraction < 1:
            raise ValueError("遥测计时线超出赛道范围。")
        starts.add(fraction)
    return np.asarray([fraction * length for fraction in sorted(starts)] + [length])


@dataclass
class Lap:
    label: str
    order: tuple
    meta: dict
    lap: dict
    distance: np.ndarray
    time: np.ndarray
    channels: dict
    splits: np.ndarray

    def at(self, channel, points):
        values = self.channels.get(channel)
        if values is None:
            return None
        return np.interp(points, self.distance, values)

    def elapsed(self, lo, hi):
        return float(np.diff(np.interp([lo, hi], self.distance, self.time))[0])

    @property
    def total(self):
        return float(self.time[-1])


def read_lap(frame, meta, lap, edges):
    """Interpolate the start and finish from the samples bracketing the line."""
    start, stop = lap["sample_start"], lap["sample_stop"]
    length = float(edges[-1])
    lo = max(0, start - 1)
    part = frame.slice(lo, stop - lo + 1)
    if stop <= start or part.height != stop - lo + 1:
        raise ValueError("缺少经过起终点的采样。")
    x = part["distance_m"].to_numpy().copy()
    t = part["time_s"].to_numpy()
    if lo < start:
        x[0] -= length
    x[-1] += length
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(t)):
        raise ValueError("圈内缺少距离或时间。")
    dx, dt = np.diff(x), np.diff(t)
    max_gap = max(.25, 5 / meta["tick_rate"])
    if (x[0] > 0 or x[-1] < length or np.any(dx < -.5) or np.any(dt <= 0) or
            np.any(dt > max_gap) or np.any(dx > np.maximum(100, dt * 150))):
        raise ValueError("圈数据不能连续对齐。")
    # Keep the first sample when distance is stationary. Minor position jitter
    # is flattened rather than using a later sample before an earlier one.
    clean_x, first = np.unique(np.maximum.accumulate(x), return_index=True)
    clean_t = t[first]
    selection = (clean_x > 0) & (clean_x < length)
    distance = np.r_[0, clean_x[selection], length]
    time = np.r_[np.interp(0, clean_x, clean_t), clean_t[selection], np.interp(length, clean_x, clean_t)]
    time -= time[0]
    if time[-1] <= 0:
        raise ValueError("圈时无法计算。")
    channels = {}
    for channel in ("speed_kph", "brake", "throttle"):
        if channel in part.columns:
            signal = part[channel].to_numpy()[first]
            if np.isfinite(signal).all():
                channels[channel] = np.interp(distance, clean_x, signal)
    recorded_at = datetime.fromisoformat(meta["start_utc"])
    order = (recorded_at.timestamp(), start, lap["recording_id"])
    label = f"{recorded_at.astimezone(ZoneInfo('America/Toronto')):%m/%d %H:%M} · 第 {lap['lap_number']} 圈"
    return Lap(label, order, meta, lap, distance, time, channels,
               np.diff(np.interp(edges, distance, time)))


def timing_rank(value, previous, *, faster_is_higher=False, official_best=False):
    if value is None:
        return ""
    if official_best:
        return "field"
    places = 1 if faster_is_higher else 3
    history = [round(v, places) for v in previous if v is not None and math.isfinite(v)]
    if not history:
        return ""
    value = round(value, places)
    improved = value > max(history) if faster_is_higher else value < min(history)
    return "personal" if improved else "ordinary"


def official_fastest_lap(trace):
    """Use the game's official race results, never infer a whole field from A/B."""
    meta, lap = trace.meta, trace.lap
    if is_simulated(meta) or meta.get("driver_car_idx") is None:
        return False
    for session in meta.get("sessions", []):
        if session.get("SessionNum") != lap["session_num"] or session.get("ResultsOfficial") not in (1, True, "1"):
            continue
        if len(session.get("ResultsPositions") or []) < 2:
            continue
        eligible = []
        for row in session.get("ResultsFastestLap") or []:
            try:
                time = float(row["FastestTime"])
                if math.isfinite(time) and time > 0:
                    eligible.append((time, row["CarIdx"], row["FastestLap"]))
            except (KeyError, ValueError, TypeError):
                continue
        if eligible:
            best = min(time for time, _, _ in eligible)
            return any(time == best and driver == meta["driver_car_idx"] and number == lap["lap_number"]
                       and abs(time - trace.total) <= .2 for time, driver, number in eligible)
    return False


def ranked(value, history, **kwargs):
    return {"value": value, "rank": timing_rank(value, history, **kwargs)}


def brake_point(trace, lo, entry):
    """First 5% pedal crossing in the region; a clipped approach is unknown."""
    inner = trace.distance[(trace.distance > lo) & (trace.distance < entry)]
    x = np.r_[lo, inner, entry]
    pedal = trace.at("brake", x)
    if pedal is None or pedal[0] >= .05:
        return None
    hits = np.flatnonzero(pedal >= .05)
    if not len(hits):
        return None
    i = int(hits[0])
    return float(np.interp(.05, pedal[i-1:i+1], x[i-1:i+1]))


def _phase_metrics(trace, lo, corner):
    entry, apex, exit_ = (float(corner[k]) for k in ("mid_start_m", "apex_m", "end_m"))
    speeds = trace.at("speed_kph", [entry, apex, exit_])
    brake = brake_point(trace, lo, entry)
    decel = None
    if brake is not None and speeds is not None:
        delta = float(trace.at("speed_kph", brake)) - float(speeds[0])
        elapsed = trace.elapsed(brake, entry)
        if elapsed > .05 and delta > 0:
            decel = delta / (3.6 * 9.80665 * elapsed)
    return [None if brake is None else apex-brake, decel] + (
        [None] * 3 if speeds is None else [float(v) for v in speeds]
    )


def window(trace_pair, history_pair, lo, hi, name, corner=None):
    grid = np.linspace(lo, hi, 161)
    traces = []
    for lap in trace_pair:
        signals = []
        for channel in ("speed_kph", "brake", "throttle"):
            values = lap.at(channel, grid)
            signals.append(None if values is None else (values * (1 if channel == "speed_kph" else 100)).round(2).tolist())
        traces.append(signals)
    metrics = []
    if corner:
        raw = [_phase_metrics(lap, lo, corner) for lap in trace_pair]
        positions = [float(corner[key]) - lo for key in ("mid_start_m", "apex_m", "end_m")]
        for i, (label, unit) in enumerate((
            ("刹车点 · 距弯心", "m"), ("平均减速度 · 到入弯", "g"),
            ("入弯速度", "km/h"), ("弯心速度", "km/h"), ("出弯速度", "km/h"),
        )):
            pair = []
            for side in range(2):
                previous = []
                if i >= 2:
                    point = lo + positions[i-2]
                    previous = [v for old in history_pair[side] if (v := old.at("speed_kph", point)) is not None]
                pair.append(ranked(raw[side][i], previous, faster_is_higher=True))
            metrics.append({"label": label, "unit": unit, "pair": pair})
    return {"name": name, "length": hi-lo, "start": lo, "traces": traces, "metrics": metrics,
            "points": positions if corner else [], "times": [lap.elapsed(lo, hi) for lap in trace_pair]}


def build_wall(before, after, records, load_samples, corners):
    """The caller chooses one shared condition bin. No demo data is injected."""
    if not before or not after:
        raise ValueError("等待两组可比的有效圈。")
    meta_a = records[before[0]["recording_id"]]["meta"]
    edges = timing_boundaries(meta_a)
    simulated = is_simulated(meta_a)
    previous_frames = {}
    rejected = 0
    groups = []
    for laps in (before, after):
        usable = []
        for lap in laps:
            record = records[lap["recording_id"]]
            meta = record["meta"]
            if compatibility(meta_a, meta):
                raise ValueError("车辆、布局、游戏版本或驾驶员不匹配。")
            if is_simulated(meta) != simulated:
                raise ValueError("请分别比较模拟与真实记录。")
            other_edges = timing_boundaries(meta)
            if len(edges) != len(other_edges) or not np.allclose(edges, other_edges, atol=.1, rtol=0):
                raise ValueError("两组记录的赛段计时线不同。")
            identifier = record["id"]
            if identifier not in previous_frames:
                previous_frames[identifier] = load_samples(record)
            try:
                usable.append(read_lap(previous_frames[identifier], meta, lap, edges))
            except ValueError:
                rejected += 1
        if not usable:
            raise ValueError("至少一组没有可连续对齐的完整圈。")
        groups.append(usable)

    pool = sorted(groups[0] + groups[1], key=lambda trace: trace.order)
    labels = [f"S{i+1}" for i in range(len(edges)-1)] if len(edges) > 2 else ["整圈窗口"]
    valid_corners = [c for c in corners if c.get("verified")]
    medians = [np.median([lap.total for lap in group]) for group in groups]
    nominal = [min(group, key=lambda lap: abs(lap.total - median)) for group, median in zip(groups, medians)]

    def previous(lap):
        return [old for old in pool if old.order < lap.order]

    def mode(theoretical):
        sectors, columns = [], []
        for i, (lo, hi) in enumerate(zip(edges, edges[1:])):
            pair = [min(group, key=lambda lap: lap.splits[i]) for group in groups] if theoretical else nominal
            histories = [previous(lap) for lap in pair]
            timed = [ranked(float(lap.splits[i]), [old.splits[i] for old in old_laps]) for lap, old_laps in zip(pair, histories)]
            columns.append(timed)
            windows = [window(pair, histories, lo, hi, "全段")]
            for c in valid_corners:
                start, apex, end = (float(c[key]) for key in ("start_m", "apex_m", "end_m"))
                if 0 <= start < apex < end <= edges[-1] and lo <= apex < hi:
                    turn = window(pair, histories, start, end, c["name"], c)
                    turn["crosses_timing_line"] = bool(start < lo or end > hi)
                    windows.append(turn)
            sectors.append({"sources": [lap.label for lap in pair], "windows": windows, "label": labels[i]})
        totals = [{"value": sum(column[i]["value"] for column in columns), "rank": ""} for i in range(2)] if theoretical else [
            ranked(lap.total, [old.total for old in previous(lap)], official_best=official_fastest_lap(lap))
            for lap in nominal
        ]
        return {"columns": columns, "sectors": sectors, "totals": totals}

    return {"labels": labels, "simulated": simulated, "rejected": rejected,
            "track": meta_a["track_name"], "car": meta_a["car_name"], "build": meta_a["build"],
            "reference": mode(False), "best": mode(True) if len(edges) > 2 else None,
            "counts": [len(group) for group in groups]}
