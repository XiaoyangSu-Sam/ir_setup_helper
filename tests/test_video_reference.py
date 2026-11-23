import numpy as np
import pytest

from endurance.storage import Store
from endurance.video_reference import compare_video, video_reference


META = {"car": "ferrari296gt3", "track_id": "262", "track": "nurburgring combinedshortb", "track_length_m": 3000.0}
CORNER = {"name": "测试弯", "start_m": 100, "apex_m": 200, "end_m": 300, "verified": True}
MARKS = {"start": "1:00.000", "apex": "64", "end": "1:06", "brake": "1:01", "throttle": "65", "speed_apex": "82"}
TRACE = {"distance_m": np.array([100, 150, 200, 250, 300]),
         "time_s": np.array([4, 6, 9, 10.5, 12]),
         "speed_kph": np.array([110, 95, 80, 88, 115]),
         "brake": np.array([0., .1, 0., 0., 0.]),
         "throttle": np.array([1., 0., 0., .1, 1.])}


def reference(marks=MARKS, continuous=True, url="https://example.com/onboard"):
    return video_reference(META, CORNER, title="教学圈", url=url, conditions="", line="留外侧出弯",
                           continuous=continuous, lap_time="8:03.250", marks=marks)


def test_annotated_video_compares_landmarks_and_keeps_original_times(tmp_path):
    ref = reference()
    store = Store(tmp_path / "video-ref")
    identifier = store.save_video_reference(ref)
    assert store.save_video_reference(ref) == identifier
    loaded = store.video_references(META["car"], META["track_id"], META["track"], CORNER["name"])
    assert loaded == {identifier: ref}
    assert not store.video_references(META["car"], META["track_id"], "different-layout", CORNER["name"])
    assert not store.list_records()
    store.close()

    compared = compare_video(ref, META, CORNER, TRACE)
    assert compared["speeds"][1] == {"key": "apex", "distance": 200., "video": 82., "own": 80., "clock": 64.}
    assert compared["events"][0] == {"key": "brake", "clock": 61., "video_m": 125., "own_m": 125.}
    assert compared["events"][1]["video_m"] == 250.
    assert compared["phases"][-1] == {"阶段": "整段", "本机秒": 8., "视频秒": 6.}
    assert ref["lap_time_s"] == 483.25


def test_missing_or_uncalibrated_readings_do_not_create_video_distance_or_timing():
    ref = reference({**MARKS, "brake": "", "speed_apex": ""}, continuous=False)
    compared = compare_video(ref, META, CORNER, TRACE)
    assert compared["aligned"] and not compared["timed"]
    assert compared["speeds"][1]["video"] is None
    assert all(event["video_m"] is None for event in compared["events"])
    assert not compared["phases"]
    changed = compare_video(reference(), META, {**CORNER, "apex_m": 201}, TRACE)
    assert not changed["aligned"] and not changed["timed"]
    assert changed["speeds"][1]["video"] == 82
    assert changed["speeds"][1]["own"] is None
    assert not compare_video(reference(), {**META, "track": "another layout"}, CORNER, TRACE)["aligned"]


@pytest.mark.parametrize("override, message", [
    ({"apex": "1:60"}, "分:秒"),
    ({"brake": 65}, "刹车点"),
    ({"throttle": 63}, "开油点"),
    ({"speed_apex": "nan"}, "500"),
])
def test_bad_video_observations_are_rejected(override, message):
    with pytest.raises(ValueError, match=message):
        reference({**MARKS, **override})
    with pytest.raises(ValueError, match="http"):
        reference(url="javascript:alert(1)")
