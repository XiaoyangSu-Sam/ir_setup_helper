"""Compare landmarks and visible inputs annotated from an onboard video."""
import math
from urllib.parse import urlsplit

import numpy as np


LANDMARKS = ("start", "apex", "end")
EVENTS = ("brake", "throttle")
DISTANCE_KEYS = ("start_m", "apex_m", "end_m")


def read_time(value):
    if value is None or not str(value).strip():
        return None
    parts = str(value).strip().replace("：", ":").split(":")
    try:
        count = float(parts[-1])
        if len(parts) == 2 and parts[0].isdigit() and 0 <= count < 60:
            count += 60 * int(parts[0])
        elif len(parts) != 1:
            raise ValueError
    except (ValueError, OverflowError):
        raise ValueError("时刻请用秒数，或用 分:秒.小数。") from None
    if not math.isfinite(count) or not 0 <= count <= 86400:
        raise ValueError("视频时刻须在 0 至 86400 秒之间。")
    return count


def _read_speed(value):
    if value is None or not str(value).strip():
        return None
    try:
        speed = float(value)
    except (TypeError, ValueError):
        raise ValueError("速度请填写画面读数，单位为 km/h。") from None
    if not math.isfinite(speed) or not 0 <= speed <= 500:
        raise ValueError("速度须在 0 至 500 km/h 之间。")
    return speed


def video_reference(meta, corner, *, title, url, conditions, line, continuous, lap_time, marks):
    title = title.strip()
    url = url.strip()
    if not title:
        raise ValueError("请为视频参考写一个名称。")
    if url:
        try:
            address = urlsplit(url)
        except ValueError:
            raise ValueError("来源链接请使用完整的 http 或 https 地址。") from None
        if (address.scheme not in {"http", "https"} or not address.hostname or
                address.username or address.password or any(ch.isspace() for ch in url)):
            raise ValueError("来源链接请使用完整的 http 或 https 地址。")

    timestamps = {key: read_time(marks.get(key)) for key in LANDMARKS + EVENTS}
    start, apex, end = (timestamps[key] for key in LANDMARKS)
    if any(point is None for point in (start, apex, end)) or not start < apex < end:
        raise ValueError("请按画面顺序标记入段、弯心和出段。")
    if timestamps["brake"] is not None and not start <= timestamps["brake"] <= apex:
        raise ValueError("刹车点应在入段与弯心之间。")
    if timestamps["throttle"] is not None and not apex <= timestamps["throttle"] <= end:
        raise ValueError("出弯开油点应在弯心与出段之间。")
    speeds = {key: _read_speed(marks.get(f"speed_{key}")) for key in LANDMARKS}
    displayed_lap = read_time(lap_time)
    if displayed_lap == 0 or (continuous and displayed_lap is not None and displayed_lap < end - start):
        raise ValueError("画面圈时应大于零，且不能短于此分段。")
    return {
        "car": meta["car"], "track_id": meta["track_id"], "track": meta["track"],
        "track_length_m": meta["track_length_m"], "corner": corner["name"],
        "anchors": [float(corner[key]) for key in DISTANCE_KEYS],
        "title": title, "url": url, "conditions": conditions.strip(), "line": line.strip(),
        "continuous": bool(continuous), "lap_time_s": displayed_lap, "times": timestamps, "speeds": speeds,
    }


def usable_landmarks(ref, meta, corner):
    return (
        corner.get("verified")
        and all(ref[key] == meta[key] for key in ("car", "track_id", "track"))
        and ref["corner"] == corner["name"]
        and abs(ref["track_length_m"] - meta["track_length_m"]) < 2
        and ref["anchors"] == [float(corner[key]) for key in DISTANCE_KEYS]
    )


def _sample(trace, channel, distance):
    x = trace["distance_m"]
    if channel in trace and x[0] <= distance <= x[-1]:
        return float(np.interp(distance, x, trace[channel]))
    return None


def _pedal_onset(trace, channel, start, end):
    if channel not in trace:
        return None
    x = trace["distance_m"]
    lo, hi = max(start, x[0]), min(end, x[-1])
    if hi <= lo:
        return None
    points = np.r_[lo, x[(x > lo) & (x < hi)], hi]
    v = np.interp(points, x, trace[channel])
    if v[0] >= .05:
        return None
    hits = np.flatnonzero(v[1:] >= .05)
    if not len(hits):
        return None
    i = hits[0]
    return float(np.interp(.05, v[i:i + 2], points[i:i + 2]))


def compare_video(ref, meta, corner, trace):
    aligned = bool(usable_landmarks(ref, meta, corner))
    timed = aligned and ref["continuous"]
    anchors = ref["anchors"]
    start, apex, end = anchors
    clocks = [ref["times"][key] for key in LANDMARKS]
    speeds = []
    for key, distance in zip(LANDMARKS, anchors):
        captured = ref["speeds"][key]
        actual = _sample(trace, "speed_kph", distance) if aligned else None
        speeds.append({"key": key, "distance": distance if aligned else None,
                       "video": captured, "own": actual, "clock": ref["times"][key]})

    events = []
    for channel, lo, hi in (("brake", start, apex), ("throttle", apex, end)):
        clock = ref["times"][channel]
        estimate = float(np.interp(clock, clocks, anchors)) if timed and clock is not None else None
        events.append({"key": channel, "clock": clock, "video_m": estimate,
                       "own_m": _pedal_onset(trace, channel, lo, hi) if aligned else None})

    phases = []
    if timed:
        for name, a, b in (("入段至弯心", 0, 1), ("弯心至出段", 1, 2), ("整段", 0, 2)):
            own = [_sample(trace, "time_s", anchors[k]) for k in (a, b)]
            video = clocks[b] - clocks[a]
            phases.append({"阶段": name, "本机秒": None if None in own else own[1] - own[0], "视频秒": video})
    return {"aligned": aligned, "timed": timed, "speeds": speeds, "events": events, "phases": phases}
