import numpy as np
import polars as pl
import pytest

from endurance.ibt import IBTError, IncompleteIBT, read_ibt
from endurance.analysis import extract_laps, pace_summary, compare_corner, validate_corners, repeated_corner


def test_real_binary_layout_and_units(make_ibt):
    r = read_ibt(make_ibt(array=True))
    assert r.samples["speed_kph"][0] == 180
    assert r.samples["steering_deg"][0] == pytest.approx(28.6478898)
    assert r.samples["lat_g"][0] == pytest.approx(1)
    assert r.samples["throttle"][0] == pytest.approx(.6)
    assert r.samples["CarIdxLap"][0].to_list() == [0, 1, 2, 3]
    assert r.metadata["track_id"] == "262"
    assert "待核实" in r.metadata["setup_scope"]


@pytest.mark.parametrize("options", [{"truncate": 4}, {"finalized": False}])
def test_incomplete_never_imported(make_ibt, options):
    with pytest.raises(IncompleteIBT):
        read_ibt(make_ibt(**options))


def test_corrupted_header(tmp_path):
    p = tmp_path / "broken.ibt"
    p.write_bytes(b"x" * 144)
    with pytest.raises(IBTError):
        read_ibt(p)


def test_unrecognized_speed_unit_rejected(make_ibt):
    with pytest.raises(IBTError, match="speed_kph"):
        read_ibt(make_ibt(unit_override=("Speed", "mph")))


def test_missing_optional_not_fabricated(make_ibt):
    r = read_ibt(make_ibt(missing=("SteeringWheelAngle", "PlayerCarMyIncidentCount")))
    _, laps = extract_laps(r.samples, r.metadata)
    assert "steering_deg" in r.metadata["missing_channels"]
    assert not any(l["valid"] for l in laps)
    assert all(l["steering_changes"] is None for l in laps)


def test_full_laps_and_errors_preserved(make_ibt):
    r = read_ibt(make_ibt(laps=5, offtrack=True))
    _, laps = extract_laps(r.samples, r.metadata)
    assert len(laps) == 6  # five completed laps plus last crossing sample
    assert sum(l["valid"] for l in laps) == 4
    assert laps[1]["offtrack"] and laps[1]["incident_delta"] == 1
    assert pace_summary(laps)["errors"] == 1
    assert laps[0]["duration_s"] == pytest.approx(60)


def test_gap_cannot_be_clean_lap(make_ibt):
    r = read_ibt(make_ibt())
    df = r.samples.filter(~pl.col("sample_index").is_between(100, 120))
    _, laps = extract_laps(df, r.metadata)
    assert not laps[0]["valid"] and laps[0]["discontinuity"]


def test_no_reference_and_distance_alignment(make_ibt):
    r = read_ibt(make_ibt())
    df, _ = extract_laps(r.samples, r.metadata)
    first = df.filter(pl.col("lap_id") == 0)
    corner = dict(start_m=100., mid_start_m=400., apex_m=500., mid_end_m=600., end_m=1000.)
    result = compare_corner(first, None, corner)
    assert not result["phases"] and result["reference"] is None
    slower = first.with_columns((pl.col("time_s") * 1.1 + 200).alias("time_s"))
    comparison = compare_corner(slower, first, corner)
    assert sum(p["差值秒"] for p in comparison["phases"]) == pytest.approx(1.8)


def test_distance_extrapolation_forbidden(make_ibt):
    r = read_ibt(make_ibt())
    df, _ = extract_laps(r.samples, r.metadata)
    part = df.filter((pl.col("lap_id") == 0) & (pl.col("distance_m") < 500))
    with pytest.raises(ValueError):
        compare_corner(part, None, dict(start_m=100, mid_start_m=400, apex_m=500, mid_end_m=600, end_m=1000))


def test_distance_interpolation_cannot_bridge_recording_gap(make_ibt):
    r = read_ibt(make_ibt())
    df, _ = extract_laps(r.samples, r.metadata)
    part = df.filter((pl.col("lap_id") == 0) & ~pl.col("sample_index").is_between(100, 120))
    with pytest.raises(ValueError, match="缺口"):
        compare_corner(part, None, dict(start_m=100, mid_start_m=400, apex_m=500, mid_end_m=600, end_m=1000))


def test_repeated_behavior_retains_error_passes(make_ibt):
    r = read_ibt(make_ibt(laps=5, offtrack=True))
    df, laps = extract_laps(r.samples, r.metadata)
    result = repeated_corner(df, laps, dict(start_m=100, end_m=1000))
    assert len(result["rows"]) == 5
    assert any("冲出赛道" in row["整圈质量"] for row in result["rows"])
    assert "不是最优速度" in result["message"]


@pytest.mark.parametrize("end,apex", [(4000, 500), (900, 950), (900, float("nan"))])
def test_corner_bounds(end, apex):
    with pytest.raises(ValueError):
        validate_corners([dict(name="test", start_m=0, mid_start_m=300, apex_m=apex, mid_end_m=700, end_m=end)], 3000)
