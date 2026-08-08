-- Canonical alert store + RF health time-series (design doc §9: "Data:
-- TimescaleDB (alerts, transcripts, RF health series)"). Applied
-- idempotently at startup (db.ensure_schema) -- see db.py's own docstring
-- for why this is a plain checked-in .sql file, not a migration
-- framework: there's no schema-evolution story yet to build tooling for.

CREATE TABLE IF NOT EXISTS alerts (
    id           TEXT PRIMARY KEY,
    state        TEXT NOT NULL,
    confidence   DOUBLE PRECISION NOT NULL,
    event_name   TEXT NOT NULL,
    fips_codes   TEXT[] NOT NULL,
    first_seen   TIMESTAMPTZ NOT NULL,
    last_updated TIMESTAMPTZ NOT NULL,
    sources      JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS alerts_last_updated_idx ON alerts (last_updated DESC);
CREATE INDEX IF NOT EXISTS alerts_state_idx ON alerts (state);

-- A real time series (continuous RF health samples), unlike alerts (discrete
-- events with occasional state transitions) -- this is the one table where
-- actually using TimescaleDB's hypertable feature, not just plain Postgres,
-- earns its keep. create_hypertable is idempotent via if_not_exists.
CREATE TABLE IF NOT EXISTS health_samples (
    site       TEXT NOT NULL,
    channel    TEXT NOT NULL,
    sampled_at TIMESTAMPTZ NOT NULL,
    rms        DOUBLE PRECISION NOT NULL,
    power      DOUBLE PRECISION NOT NULL,
    dead       BOOLEAN NOT NULL
);

SELECT create_hypertable('health_samples', 'sampled_at', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS health_samples_site_channel_time_idx
    ON health_samples (site, channel, sampled_at DESC);
