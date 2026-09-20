DROP TABLE IF EXISTS coverages;
DROP TABLE IF EXISTS policies;
DROP TABLE IF EXISTS locations;

CREATE TABLE locations (
    location_id     INTEGER PRIMARY KEY,
    latitude        REAL NOT NULL,
    longitude       REAL NOT NULL,
    county          TEXT NOT NULL,          -- Miami-Dade, Broward, or Palm Beach
    construction_class TEXT NOT NULL,       -- HAZUS Hurricane Model building classes
    occupancy       TEXT NOT NULL,          -- Residential (this portfolio is residential-only)
    year_built      INTEGER NOT NULL,
    num_stories     INTEGER NOT NULL
);

CREATE TABLE policies (
    policy_id       INTEGER PRIMARY KEY,
    location_id     INTEGER NOT NULL REFERENCES locations(location_id),
    total_insured_value REAL NOT NULL,      -- TIV in USD, building coverage only at this table level
    deductible_pct  REAL NOT NULL           -- hurricane deductible as % of TIV (FL practice: 2-10%)
);

CREATE TABLE coverages (
    coverage_id     INTEGER PRIMARY KEY,
    policy_id       INTEGER NOT NULL REFERENCES policies(policy_id),
    coverage_type   TEXT NOT NULL,          -- 'Building', 'Contents', 'ALE'
    coverage_value  REAL NOT NULL
);

CREATE INDEX idx_locations_county ON locations(county);
CREATE INDEX idx_locations_construction ON locations(construction_class);
CREATE INDEX idx_policies_location ON policies(location_id);
CREATE INDEX idx_coverages_policy ON coverages(policy_id);
