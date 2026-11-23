from copy import deepcopy

import polars as pl
import pytest

from endurance.storage import Store
from endurance.timing_wall import build_wall, common_conditions, official_fastest_lap, read_lap, timing_boundaries


def test_splits_interpolate_timing_lines_and_preserve_missing_channels():
    frame = pl.DataFrame({"distance_m": [2950., 10., 1000., 2600., 40.],
                          "time_s": [0., 1., 10., 22., 25.], "speed_kph": [85., 80., 90., 100., 105.]})
    meta = {"track_length_m": 3000., "sectors": [{"SectorStartPct": .5}],
            "start_utc": "2026-11-02T12:00:00+00:00", "tick_rate": .1}
    lap = {"sample_start": 1, "sample_stop": 4, "recording_id": "sample", "lap_number": 12}
    trace = read_lap(frame, meta, lap, timing_boundaries(meta))
    expected = (22 + 3 * 400 / 440) - (50 / 60)
    assert trace.total == pytest.approx(expected)
    assert trace.splits.sum() == pytest.approx(trace.total)
    assert trace.at("brake", 1500) is None
    with pytest.raises(ValueError, match="不能连续对齐"):
        read_lap(frame, {**meta, "tick_rate": 60}, lap, timing_boundaries(meta))


def test_wall_only_ranks_official_whole_laps_and_keeps_theoretical_total_neutral(make_ibt, tmp_path):
    store = Store(tmp_path / "timing-library")
    a, _ = store.import_file(make_ibt(sectors=(0., .3, .7)))
    b, _ = store.import_file(make_ibt(name="after.ibt", sectors=(0., .3, .7), lap_seconds=58, epoch=1700000100, missing=("Brake",)))
    records = {r["id"]: r for r in store.list_records()}
    before, after = next(iter(common_conditions(records[a]["laps"], records[b]["laps"]).values()))
    after_meta = records[b]["meta"]
    after_meta["sessions"] = [{"SessionNum": 0, "ResultsOfficial": 1, "ResultsPositions": [{"CarIdx": 0}, {"CarIdx": 1}],
                              "ResultsFastestLap": [{"CarIdx": 0, "FastestLap": 1, "FastestTime": 58.}]}]
    load = lambda record: pl.read_parquet(store.root / "recordings" / f"{record['id']}.parquet")
    corner = {"name": "已校准弯道", "verified": True, "start_m": 100, "mid_start_m": 200, "apex_m": 300, "end_m": 400}
    wall = build_wall(before, after, records, load, [corner])
    assert wall["labels"] == ["S1", "S2", "S3"]
    assert wall["reference"]["totals"][1] == {"value": 58., "rank": "field"}
    assert wall["reference"]["columns"][0][1]["rank"] == "personal"
    turn = wall["reference"]["sectors"][0]["windows"][1]
    assert turn["traces"][1][1] is None
    assert turn["metrics"][3]["pair"][1]["rank"] == "personal"
    assert wall["best"]["totals"][1] == {"value": pytest.approx(58.), "rank": ""}

    trace = read_lap(load(records[b]), after_meta, after[0], timing_boundaries(after_meta))
    assert official_fastest_lap(trace)
    trace.meta = deepcopy(after_meta)
    trace.meta["sessions"][0]["ResultsFastestLap"].append({"CarIdx": 1, "FastestLap": 2, "FastestTime": 56.})
    assert not official_fastest_lap(trace)
    after_meta["simulated"] = True
    with pytest.raises(ValueError, match="分别比较"):
        build_wall(before, after, records, load, [])
    store.close()
