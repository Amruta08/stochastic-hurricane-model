"""
Module 1: Synthetic Exposure Portfolio Generator
==================================================
Generates a synthetic residential property portfolio across Miami-Dade, Broward,
and Palm Beach counties (FL) and loads it into the SQLite exposure database.
"""

import sqlite3
import numpy as np
from pathlib import Path

# Reproducibility: fixed seed so anyone re-running this gets the identical portfolio
RNG = np.random.default_rng(seed=42)

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "portfolio.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "sql" / "schema.sql"

N_LOCATIONS = 5000

# Approximate bounding boxes (min_lat, max_lat, min_lon, max_lon).
# APPROXIMATE ONLY - see module docstring honesty note above.
COUNTY_BOUNDS = {
    "Miami-Dade": (25.14, 25.97, -80.87, -80.11),
    "Broward":    (25.97, 26.44, -80.89, -80.06),
    "Palm Beach": (26.32, 26.97, -80.87, -80.03),
}
# Rough relative population/exposure weighting across the 3 counties -
# Miami-Dade and Broward are more densely built up than Palm Beach.
COUNTY_WEIGHTS = {"Miami-Dade": 0.42, "Broward": 0.35, "Palm Beach": 0.23}

CONSTRUCTION_CLASSES = ["Masonry", "Wood Frame", "Manufactured Home"]
# Reflects post-Hurricane Andrew (1992) building code shift toward masonry
# in South FL - illustrative assumption, not a cited statistic (see docstring).
CONSTRUCTION_WEIGHTS = [0.55, 0.40, 0.05]

# Typical FL residential hurricane deductible is a percentage of TIV, commonly
# 2%, 5%, or 10% (this is a well-documented FL insurance market practice, not
# a modeled assumption - see Florida Office of Insurance Regulation consumer
# guidance on hurricane deductibles).
DEDUCTIBLE_OPTIONS = [0.02, 0.05, 0.10]
DEDUCTIBLE_WEIGHTS = [0.5, 0.35, 0.15]


def sample_county(n):
    return RNG.choice(list(COUNTY_WEIGHTS.keys()), size=n, p=list(COUNTY_WEIGHTS.values()))


def sample_coords(counties):
    lats = np.empty(len(counties))
    lons = np.empty(len(counties))
    for county, (min_lat, max_lat, min_lon, max_lon) in COUNTY_BOUNDS.items():
        mask = counties == county
        n = mask.sum()
        lats[mask] = RNG.uniform(min_lat, max_lat, n)
        lons[mask] = RNG.uniform(min_lon, max_lon, n)
    return lats, lons


def sample_tiv(construction_classes, year_built):
    base_median = np.where(construction_classes == "Masonry", 380_000,
                   np.where(construction_classes == "Wood Frame", 320_000, 150_000))
    age_factor = 1 + (year_built - 1970) / 1000  # newer homes worth slightly more
    median = base_median * age_factor
    sigma = 0.5  # lognormal shape parameter controlling spread
    tiv = RNG.lognormal(mean=np.log(median), sigma=sigma)
    return np.clip(tiv, 75_000, 3_000_000)  # floor/cap to keep values plausible


def build_portfolio():
    counties = sample_county(N_LOCATIONS)
    lats, lons = sample_coords(counties)
    construction = RNG.choice(CONSTRUCTION_CLASSES, size=N_LOCATIONS, p=CONSTRUCTION_WEIGHTS)
    year_built = RNG.integers(1960, 2023, N_LOCATIONS)
    # Manufactured homes are almost never multi-story; masonry/wood frame usually 1-2.
    num_stories = np.where(
        construction == "Manufactured Home", 1,
        RNG.integers(1, 3, N_LOCATIONS)
    )
    tiv = sample_tiv(construction, year_built)
    deductible = RNG.choice(DEDUCTIBLE_OPTIONS, size=N_LOCATIONS, p=DEDUCTIBLE_WEIGHTS)

    return {
        "county": counties, "lat": lats, "lon": lons,
        "construction": construction, "year_built": year_built,
        "num_stories": num_stories, "tiv": tiv, "deductible": deductible,
    }


def load_to_sqlite(portfolio):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Rebuild schema fresh every run - keeps this script idempotent/reproducible.
    with open(SCHEMA_PATH) as f:
        cur.executescript(f.read())

    n = N_LOCATIONS
    locations_rows = [
        (i + 1, portfolio["lat"][i], portfolio["lon"][i], portfolio["county"][i],
         portfolio["construction"][i], "Residential", int(portfolio["year_built"][i]),
         int(portfolio["num_stories"][i]))
        for i in range(n)
    ]
    cur.executemany(
        "INSERT INTO locations VALUES (?,?,?,?,?,?,?,?)", locations_rows
    )

    policies_rows = [
        (i + 1, i + 1, float(portfolio["tiv"][i]), float(portfolio["deductible"][i]))
        for i in range(n)
    ]
    cur.executemany(
        "INSERT INTO policies VALUES (?,?,?,?)", policies_rows
    )

    # Standard FL residential coverage split: Building ~75% of TIV headline value,
    # Contents ~25% of building value, ALE ~10% of building value. These ratios
    # follow common HO-3 policy structuring conventions (illustrative, not a
    # cited filing - flag as assumption if asked).
    coverage_id = 1
    coverage_rows = []
    for i in range(n):
        building = portfolio["tiv"][i]
        contents = building * 0.25
        ale = building * 0.10
        for cov_type, val in [("Building", building), ("Contents", contents), ("ALE", ale)]:
            coverage_rows.append((coverage_id, i + 1, cov_type, float(val)))
            coverage_id += 1
    cur.executemany(
        "INSERT INTO coverages VALUES (?,?,?,?)", coverage_rows
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    portfolio = build_portfolio()
    load_to_sqlite(portfolio)
    print(f"Portfolio built: {N_LOCATIONS} locations -> {DB_PATH}")
