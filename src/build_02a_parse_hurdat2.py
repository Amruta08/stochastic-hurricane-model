"""
Module 2a: HURDAT2 Parser
==========================
Parses the raw NOAA HURDAT2 best-track file into structured storm records.
"""

import re
from pathlib import Path
from dataclasses import dataclass, field

RAW_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "hurdat2.txt"


@dataclass
class TrackPoint:
    date: str          # YYYYMMDD
    time: str          # HHMM
    record_id: str      # 'L' = landfall, else blank/other flag
    status: str         # HU, TS, TD, EX, etc.
    lat: float
    lon: float
    wind_kt: int
    pressure_mb: int    # -999 if missing in source data


@dataclass
class Storm:
    storm_id: str
    name: str
    track: list = field(default_factory=list)  # list[TrackPoint]


def _parse_latlon(lat_str, lon_str):
    """'28.0N' -> 28.0 ; '94.8W' -> -94.8 (negative = West, standard convention)."""
    lat = float(lat_str[:-1])
    if lat_str[-1] == "S":
        lat = -lat
    lon = float(lon_str[:-1])
    if lon_str[-1] == "W":
        lon = -lon
    return lat, lon


def parse_hurdat2(path=RAW_PATH):
    storms = []
    with open(path) as f:
        lines = [l.strip() for l in f if l.strip()]

    i = 0
    while i < len(lines):
        header = lines[i]
        # Header lines start with a basin+number ID like AL011851
        if re.match(r"^(AL|EP|CP)\d{6},", header):
            parts = [p.strip() for p in header.split(",")]
            storm_id, name, n_entries = parts[0], parts[1], int(parts[2])
            storm = Storm(storm_id=storm_id, name=name)
            for j in range(1, n_entries + 1):
                fields = [f.strip() for f in lines[i + j].split(",")]
                lat, lon = _parse_latlon(fields[4], fields[5])
                storm.track.append(TrackPoint(
                    date=fields[0], time=fields[1], record_id=fields[2],
                    status=fields[3], lat=lat, lon=lon,
                    wind_kt=int(fields[6]), pressure_mb=int(fields[7]),
                ))
            storms.append(storm)
            i += n_entries + 1
        else:
            i += 1  # safety skip, shouldn't normally trigger
    return storms


if __name__ == "__main__":
    storms = parse_hurdat2()
    print(f"Parsed {len(storms)} storms, {sum(len(s.track) for s in storms)} total track points.")
    # Sanity check: print the first storm's first point
    s0 = storms[0]
    print(f"First storm: {s0.storm_id} {s0.name}, {len(s0.track)} points")
    print(s0.track[0])
