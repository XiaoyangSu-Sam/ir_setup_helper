from pathlib import Path
import struct

import numpy as np
import pytest
import yaml


@pytest.fixture
def make_ibt(tmp_path):
    def make(name="sample.ibt", laps=5, offtrack=False, missing=(), truncate=0, finalized=True, unit_override=None, array=False, lap_seconds=60, front_arb=30, build="test.1", epoch=1700000000, sectors=(0.,)):
        samples_per_lap = round(lap_seconds * 10)
        count = laps * samples_per_lap + 1
        t = np.arange(count) / 10
        pct = (np.arange(count) % samples_per_lap) / samples_per_lap
        raw = {
            "SessionTime": (5, "s", t), "SessionNum": (2, "", np.zeros(count)),
            "Lap": (2, "", np.arange(count) // samples_per_lap + 1), "LapDistPct": (4, "%", pct),
            "Speed": (4, "m/s", np.full(count, 3000 / lap_seconds)), "Throttle": (4, "%", np.full(count, .6)),
            "Brake": (4, "%", np.full(count, .1)), "SteeringWheelAngle": (4, "rad", np.full(count, .5)),
            "FuelLevel": (4, "l", np.full(count, 81.)), "TrackTemp": (4, "C", np.full(count, 31.)),
            "AirTemp": (4, "C", np.full(count, 22.)), "TrackWetness": (2, "irsdk_TrackWetness", np.ones(count)),
            "OnPitRoad": (1, "", np.zeros(count)), "PlayerTrackSurface": (2, "irsdk_TrkLoc", np.full(count, 3)),
            "PlayerCarMyIncidentCount": (2, "", np.zeros(count)), "PlayerTireCompound": (2, "", np.zeros(count)),
            "PlayerCarWeightPenalty": (4, "kg", np.zeros(count)), "PlayerCarPowerAdjust": (4, "%", np.zeros(count)),
            "LatAccel": (4, "m/s^2", np.full(count, 9.80665)),
        }
        if offtrack:
            raw["PlayerTrackSurface"][2][650:660] = 0
            raw["PlayerCarMyIncidentCount"][2][650:] = 1
        for key in missing:
            raw.pop(key)
        if unit_override:
            key, unit = unit_override
            typ, _, data = raw[key]
            raw[key] = typ, unit, data
        if array:
            raw["CarIdxLap"] = (2, "", np.tile(np.arange(4), (count, 1)))
        fmt = {1: "?", 2: "<i4", 4: "<f4", 5: "<f8"}
        dtype = np.dtype([(key, fmt[typ], (() if data.ndim == 1 else (data.shape[1],))) for key, (typ, unit, data) in raw.items()])
        records = np.zeros(count, dtype=dtype)
        variables = bytearray()
        for key, (typ, unit, data) in raw.items():
            records[key] = data
            vh = bytearray(144)
            struct.pack_into("<iii", vh, 0, typ, dtype.fields[key][1], 1 if data.ndim == 1 else data.shape[1])
            vh[16:16 + len(key)] = key.encode()
            vh[112:112 + len(unit)] = unit.encode()
            variables += vh
        session = {
            "WeekendInfo": {"TrackID": 262, "TrackName": "nurburgring combinedshortb", "TrackLength": "3.000 km", "BuildVersion": build},
            "DriverInfo": {"DriverCarIdx": 0, "DriverCarFuelMaxLtr": 104, "Drivers": [{"CarIdx": 0, "CarPath": "ferrari296gt3", "UserID": 123}]},
            "CarSetup": {"TiresAero": {"TireType": {"TireType": "Dry"}}, "Chassis": {"FrontBrakesLights": {"ArbBlades": f"{front_arb} degrees", "ArbOptions": "Large"}}},
            "SplitTimeInfo": {"Sectors": [{"SectorNum": i, "SectorStartPct": pct} for i, pct in enumerate(sectors)]},
        }
        y = yaml.safe_dump(session).encode()
        soff = 144 + len(variables)
        data_offset = soff + len(y)
        header = bytearray(144)
        struct.pack_into("<10i", header, 0, 2, 1, 10, 0, len(y), soff, len(raw), 144, 1, dtype.itemsize)
        struct.pack_into("<i", header, 52, data_offset)
        struct.pack_into("<qddii", header, 112, epoch, 0., float(t[-1]) if finalized else 0., laps, count if finalized else 0)
        payload = header + variables + y + records.tobytes()
        if truncate:
            payload = payload[:-truncate]
        path = tmp_path / name
        path.write_bytes(payload)
        return path
    return make
