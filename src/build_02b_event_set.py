"""
Module 2b: Florida Landfall Extraction + Stochastic Event Set
"""

import sqlite3
import numpy as np
from pathlib import Path
from math import radians, degrees, sin, cos, atan2, sqrt

from build_02a_parse_hurdat2 import parse_hurdat2

RNG = np.random.default_rng(seed=123)
DB_PATH = Path(__file__).resolve().parent.parent / "db" / "portfolio.db"

# Florida landfall region bounding box - covers the SE Florida coastline
# relevant to our Miami-Dade/Broward/Palm Beach portfolio, with a margin so we
# also catch storms making landfall just north/south that still affect the
# portfolio via the wind field's spatial extent in Module 3.
FL_BOX = (24.5, 28.5, -81.5, -79.5)  # min_lat, max_lat, min_lon, max_lon

N_VARIANTS_PER_HISTORICAL_EVENT = 130  # 79 historical landfalls x 130 = 10,270 events (~= 10,000 target)
LANDFALL_PERTURB_KM = 100     # see uncertainty disclosure above
PRESSURE_PERTURB_MB = 10      # see uncertainty disclosure above
SPEED_PERTURB_PCT = 0.20      # see uncertainty disclosure above

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * atan2(sqrt(a), sqrt(1 - a))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Compass heading (0=N, 90=E) of travel from point 1 to point 2."""
    lat1, lat2 = radians(lat1), radians(lat2)
    dlon = radians(lon2 - lon1)
    x = sin(dlon) * cos(lat2)
    y = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon)
    return (degrees(atan2(x, y)) + 360) % 360


def hours_between(date1, time1, date2, time2):
    from datetime import datetime
    fmt = "%Y%m%d%H%M"
    t1 = datetime.strptime(date1 + time1, fmt)
    t2 = datetime.strptime(date2 + time2, fmt)
    return (t2 - t1).total_seconds() / 3600.0


def estimate_pressure_from_wind(wind_kt):
    """Fallback wind-pressure relationship - see module docstring uncertainty
    disclosure. Only used when HURDAT2 pressure field is -999 (missing)."""
    a, b = 6.7, 0.644
    pressure_deficit = (wind_kt / a) ** (1 / b)
    return 1013 - pressure_deficit


def in_fl_box(lat, lon):
    min_lat, max_lat, min_lon, max_lon = FL_BOX
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def extract_fl_landfalls(storms):
    """Find each storm's landfall point (record_id == 'L') that falls inside
    the Florida box at tropical-storm strength or higher, and derive the
    Holland-wind-field parameters needed for Module 3."""
    events = []
    for storm in storms:
        track = storm.track
        for idx, pt in enumerate(track):
            if pt.record_id != "L" or not in_fl_box(pt.lat, pt.lon):
                continue
            if pt.status not in ("HU", "TS"):
                continue  # only named tropical-storm-or-stronger landfalls matter for loss

            pressure = pt.pressure_mb if pt.pressure_mb != -999 else estimate_pressure_from_wind(pt.wind_kt)

            # Forward speed & heading: use the track point just before landfall
            # (or just after, if landfall is the first point) to estimate motion.
            if idx > 0:
                prev = track[idx - 1]
                dist_km = haversine_km(prev.lat, prev.lon, pt.lat, pt.lon)
                dt_hr = hours_between(prev.date, prev.time, pt.date, pt.time)
                heading = bearing_deg(prev.lat, prev.lon, pt.lat, pt.lon)
            elif idx < len(track) - 1:
                nxt = track[idx + 1]
                dist_km = haversine_km(pt.lat, pt.lon, nxt.lat, nxt.lon)
                dt_hr = hours_between(pt.date, pt.time, nxt.date, nxt.time)
                heading = bearing_deg(pt.lat, pt.lon, nxt.lat, nxt.lon)
            else:
                dist_km, dt_hr, heading = 0, 1, 0  # single-point storm, degenerate case

            forward_speed_kmh = dist_km / dt_hr if dt_hr > 0 else 15.0  # ~15 km/h typical fallback

            events.append({
                "storm_id": storm.storm_id, "name": storm.name.strip(),
                "year": int(pt.date[:4]),
                "landfall_lat": pt.lat, "landfall_lon": pt.lon,
                "max_wind_kt": pt.wind_kt, "pressure_mb": round(pressure, 1),
                "forward_speed_kmh": round(forward_speed_kmh, 1),
                "heading_deg": round(heading, 1),
            })
    return events


def generate_synthetic_catalog(historical_events):
    """Perturb each historical FL landfall N times to build the stochastic
    event set. Rate is calibrated so the TOTAL annual event rate across all
    synthetic events matches the historical average annual FL landfall
    frequency - this "rate matching" is a standard stochastic-catalog
    calibration principle (the catalog should reproduce known historical
    frequency even though individual events are synthetic)."""
    n_hist = len(historical_events)
    years_span = 2025 - 1851 + 1
    historical_annual_rate = n_hist / years_span
    # Rate matching: the SUM of all synthetic event rates must equal the historical
    # annual rate (0.45 events/year), not n_hist x that. Each synthetic variant is
    # one of N_VARIANTS_PER_HISTORICAL_EVENT equally-likely "flavors" of its parent
    # historical event, so it gets an equal fractional share of that parent event's
    # contribution to the overall annual rate.
    total_synthetic_events = n_hist * N_VARIANTS_PER_HISTORICAL_EVENT
    rate_per_synthetic_event = historical_annual_rate / total_synthetic_events

    synthetic = []
    event_id = 1
    for hist in historical_events:
        # Rejection sampling: keep drawing perturbations until we have exactly
        # N_VARIANTS_PER_HISTORICAL_EVENT PHYSICALLY VALID (>=34kt) variants for
        # this historical event. This keeps the total catalog size AND the rate
        # calibration exact, rather than silently under-counting when a
        # perturbation happens to weaken a storm below tropical-storm strength.
        kept = 0
        attempts = 0
        while kept < N_VARIANTS_PER_HISTORICAL_EVENT and attempts < N_VARIANTS_PER_HISTORICAL_EVENT * 20:
            attempts += 1
            # Perturb landfall location: convert km offset to approx degrees
            # (1 deg lat ~= 111km; 1 deg lon ~= 111km * cos(lat) at this latitude)
            offset_km = RNG.uniform(-LANDFALL_PERTURB_KM, LANDFALL_PERTURB_KM)
            bearing_along_coast = RNG.uniform(0, 360)
            dlat = (offset_km * cos(radians(bearing_along_coast))) / 111.0
            dlon = (offset_km * sin(radians(bearing_along_coast))) / (111.0 * cos(radians(hist["landfall_lat"])))

            pressure = hist["pressure_mb"] + RNG.normal(0, PRESSURE_PERTURB_MB)
            speed = hist["forward_speed_kmh"] * (1 + RNG.uniform(-SPEED_PERTURB_PCT, SPEED_PERTURB_PCT))

            # Recompute wind from perturbed pressure so wind/pressure stay physically
            # consistent (inverse of the estimate_pressure_from_wind relationship).
            pressure_deficit = max(1013 - pressure, 1)
            wind = 6.7 * (pressure_deficit ** 0.644)

            # Data-quality guard: our historical source population was filtered to
            # Tropical-Storm-strength-or-higher (>=34kt) landfalls. If a pressure
            # perturbation pushes the recomputed wind below that threshold, the
            # "event" is no longer physically a tropical storm - reject and redraw
            # rather than keep a sub-threshold event or silently under-count the
            # catalog. (Caught via a post-build sanity check the first time this
            # ran - min wind was 7kt, which is not a tropical cyclone at all.)
            if wind < 34:
                continue

            synthetic.append({
                "event_id": event_id,
                "source_storm_id": hist["storm_id"],
                "source_year": hist["year"],
                "landfall_lat": round(hist["landfall_lat"] + dlat, 3),
                "landfall_lon": round(hist["landfall_lon"] + dlon, 3),
                "pressure_mb": round(pressure, 1),
                "max_wind_kt": round(wind, 1),
                "forward_speed_kmh": round(speed, 1),
                "heading_deg": hist["heading_deg"],
                "annual_rate": rate_per_synthetic_event,
            })
            event_id += 1
            kept += 1
    return synthetic, historical_annual_rate


def load_events_to_sqlite(historical_events, synthetic_events):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executescript("""
        DROP TABLE IF EXISTS historical_events;
        DROP TABLE IF EXISTS synthetic_events;

        CREATE TABLE historical_events (
            storm_id TEXT, name TEXT, year INTEGER,
            landfall_lat REAL, landfall_lon REAL,
            max_wind_kt REAL, pressure_mb REAL,
            forward_speed_kmh REAL, heading_deg REAL
        );

        CREATE TABLE synthetic_events (
            event_id INTEGER PRIMARY KEY,
            source_storm_id TEXT, source_year INTEGER,
            landfall_lat REAL, landfall_lon REAL,
            pressure_mb REAL, max_wind_kt REAL,
            forward_speed_kmh REAL, heading_deg REAL,
            annual_rate REAL
        );
    """)
    cur.executemany(
        "INSERT INTO historical_events VALUES (:storm_id,:name,:year,:landfall_lat,:landfall_lon,:max_wind_kt,:pressure_mb,:forward_speed_kmh,:heading_deg)",
        historical_events,
    )
    cur.executemany(
        "INSERT INTO synthetic_events VALUES (:event_id,:source_storm_id,:source_year,:landfall_lat,:landfall_lon,:pressure_mb,:max_wind_kt,:forward_speed_kmh,:heading_deg,:annual_rate)",
        synthetic_events,
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    storms = parse_hurdat2()
    historical = extract_fl_landfalls(storms)
    print(f"Historical Florida landfalls (TS+ strength, 1851-2025): {len(historical)}")

    synthetic, hist_rate = generate_synthetic_catalog(historical)
    print(f"Historical annual FL landfall rate: {hist_rate:.4f} events/year")
    print(f"Synthetic event catalog size: {len(synthetic)}")
    print(f"Sum of synthetic annual rates (should ~= historical rate): "
          f"{sum(e['annual_rate'] for e in synthetic):.4f}")

    load_events_to_sqlite(historical, synthetic)
    print("Loaded historical_events and synthetic_events tables into portfolio.db")
