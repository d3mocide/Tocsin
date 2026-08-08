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

-- The third thing design doc §9 names for TimescaleDB ("alerts,
-- transcripts, RF health series") and the last to be built. Keyed on
-- (raw_header, timestamp_ns) rather than a surrogate id: stt_worker
-- publishes no id of its own, and the SAME header plus the transcription
-- time is what actually identifies one transcription attempt. That
-- composite is also what makes redelivery on the at-least-once stream
-- idempotent.
--
-- `text` is empty whenever `passed_guard` is false -- stt_worker
-- deliberately drops the text of a transcript that looks hallucinated
-- rather than passing it on (see its service.py). `guard_reason` is
-- therefore the only record of *why*, and is worth showing in the UI: a
-- guard-failed transcript is exactly the one where someone will want to
-- play the original audio.
CREATE TABLE IF NOT EXISTS transcripts (
    raw_header   TEXT NOT NULL,
    timestamp_ns BIGINT NOT NULL,
    site         TEXT NOT NULL,
    channel      TEXT NOT NULL,
    event_code   TEXT NOT NULL,
    tier         TEXT NOT NULL,
    fips_codes   TEXT[] NOT NULL,
    text         TEXT NOT NULL,
    passed_guard BOOLEAN NOT NULL,
    guard_reason TEXT,
    wav_path     TEXT,
    PRIMARY KEY (raw_header, timestamp_ns)
);

CREATE INDEX IF NOT EXISTS transcripts_time_idx ON transcripts (timestamp_ns DESC);

-- What dispatcher decided, including every negative outcome
-- (skipped_not_tier_a, skipped_duplicate, skipped_rate_limited,
-- skipped_already_sent, serial_no_ack, ...). This is the only table that
-- records what Tocsin *did* rather than what it observed, and it is what
-- makes "did that warning actually reach the mesh?" answerable without
-- reading container logs.
--
-- No primary key: dispatcher legitimately produces several rows for the
-- same (raw_header, stage) over time -- a rate-limited attempt followed
-- by a later successful one is two real events, not a duplicate to
-- collapse. Redelivery of the same stream entry can therefore double a
-- row here; that is the accepted cost of keeping the retry history, and
-- the reason this feeds a UI log rather than any dispatch decision.
CREATE TABLE IF NOT EXISTS dispatches (
    dispatched_at TIMESTAMPTZ NOT NULL,
    stage         TEXT NOT NULL,
    alert_id      TEXT,
    site          TEXT,
    channel       TEXT,
    event_code    TEXT NOT NULL,
    tier          TEXT NOT NULL,
    fips_codes    TEXT[] NOT NULL,
    raw_header    TEXT NOT NULL,
    sent          BOOLEAN NOT NULL,
    reason        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS dispatches_time_idx ON dispatches (dispatched_at DESC);
CREATE INDEX IF NOT EXISTS dispatches_raw_header_idx ON dispatches (raw_header);
