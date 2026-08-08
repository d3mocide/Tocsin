"""Postgres (TimescaleDB) access -- the first thing in this repo to
actually write to the `timescaledb` compose service (design doc §9:
"Data: TimescaleDB (alerts, transcripts, RF health series)"). Every prior
phase's canonical-alert/health-signal work has deliberately stood in with
a `Logging*Sink` because standing up a real schema/writer wasn't that
phase's dependency (see e.g. `sdr_rx.health`'s original docstring) -- this
is where that finally happens.

Raw asyncpg, no ORM/migration framework: the schema (`schema.sql`) is a
handful of simple tables with no schema-evolution story yet, so
SQLAlchemy+Alembic's weight isn't earning its keep here (CLAUDE.md: don't
build abstractions for a problem that doesn't exist yet).

Every function takes an explicit `pool` argument rather than importing a
module-level global -- the same injectable-dependency shape every other
service in this repo uses (a `pool`-like object is easy to fake in tests;
`asyncpg.Pool` itself already exposes `execute`/`fetch`/`fetchrow`
directly with no `.acquire()` boilerplate needed for these simple
queries, so the real thing satisfies `PoolLike` with no wrapping).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class PoolLike(Protocol):
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...


async def ensure_schema(pool: PoolLike, schema_path: Path = SCHEMA_PATH) -> None:
    statements = [s.strip() for s in schema_path.read_text().split(";") if s.strip()]
    for statement in statements:
        await pool.execute(statement)


async def upsert_alert(pool: PoolLike, alert: dict) -> None:
    """`alert` is `fusion`'s `tocsin:alerts` wire payload (service
    boundary -- duplicated shape knowledge, not a shared import). Upserts
    on `id` because the same alert is republished on every state
    transition (`RF_ONLY` -> `CONFIRMED`), not just once.

    `first_seen`/`last_updated` arrive as ISO-8601 strings (JSON has no
    native datetime type) -- asyncpg needs a real `datetime` for a
    `timestamptz` parameter, it does not parse strings implicitly."""
    await pool.execute(
        """
        INSERT INTO alerts (id, state, confidence, event_name, fips_codes, first_seen, last_updated, sources)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (id) DO UPDATE SET
            state = EXCLUDED.state,
            confidence = EXCLUDED.confidence,
            last_updated = EXCLUDED.last_updated,
            sources = EXCLUDED.sources
        """,
        alert["id"],
        alert["state"],
        alert["confidence"],
        alert["event_name"],
        list(alert["fips_codes"]),
        datetime.fromisoformat(alert["first_seen"]),
        datetime.fromisoformat(alert["last_updated"]),
        json.dumps(alert["sources"]),
    )


async def insert_health_sample(pool: PoolLike, health: dict) -> None:
    """`health` is `sdr_rx`'s `tocsin:health` wire payload."""
    await pool.execute(
        """
        INSERT INTO health_samples (site, channel, sampled_at, rms, power, dead)
        VALUES ($1, $2, to_timestamp($3 / 1e9), $4, $5, $6)
        """,
        health["site"],
        health["channel"],
        health["timestamp_ns"],
        health["rms"],
        health["power"],
        health["dead"],
    )


async def insert_transcript(pool: PoolLike, transcript: dict) -> None:
    """`transcript` is `stt_worker`'s `tocsin:transcripts` wire payload.
    `ON CONFLICT DO NOTHING` on the (raw_header, timestamp_ns) key makes a
    redelivered stream entry a no-op -- the consumer group is at-least-once
    (see `redis_bus.py`), and re-inserting the same transcription would
    otherwise show up as a duplicate in the UI."""
    await pool.execute(
        """
        INSERT INTO transcripts (
            raw_header, timestamp_ns, site, channel, event_code, tier,
            fips_codes, text, passed_guard, guard_reason, wav_path
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        ON CONFLICT (raw_header, timestamp_ns) DO NOTHING
        """,
        transcript["raw_header"],
        transcript["timestamp_ns"],
        transcript["site"],
        transcript["channel"],
        transcript["event_code"],
        transcript["tier"],
        list(transcript["fips_codes"]),
        transcript["text"],
        transcript["passed_guard"],
        transcript.get("guard_reason"),
        transcript.get("wav_path"),
    )


async def insert_dispatch(pool: PoolLike, dispatch: dict) -> None:
    """`dispatch` is `dispatcher`'s `tocsin:dispatches` wire payload. Stage
    1 records carry `alert_id`; stage 2 records carry `site`/`channel`
    instead (see dispatcher's `redis_sink._serialize`), so both are
    optional here."""
    await pool.execute(
        """
        INSERT INTO dispatches (
            dispatched_at, stage, alert_id, site, channel,
            event_code, tier, fips_codes, raw_header, sent, reason
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """,
        datetime.fromisoformat(dispatch["dispatched_at"]),
        dispatch["stage"],
        dispatch.get("alert_id"),
        dispatch.get("site"),
        dispatch.get("channel"),
        dispatch["event_code"],
        dispatch["tier"],
        list(dispatch["fips_codes"]),
        dispatch["raw_header"],
        dispatch["sent"],
        dispatch["reason"],
    )


async def list_alerts(pool: PoolLike, limit: int = 100, state: str | None = None) -> list[dict]:
    if state:
        rows = await pool.fetch(
            "SELECT * FROM alerts WHERE state = $1 ORDER BY last_updated DESC LIMIT $2", state, limit
        )
    else:
        rows = await pool.fetch("SELECT * FROM alerts ORDER BY last_updated DESC LIMIT $1", limit)
    return [_alert_row_to_dict(row) for row in rows]


def _alert_row_to_dict(row: Any) -> dict:
    data = dict(row)
    sources = data.get("sources")
    if isinstance(sources, str):
        data["sources"] = json.loads(sources)
    return data


async def latest_health(pool: PoolLike) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (site, channel) site, channel, sampled_at, rms, power, dead
        FROM health_samples
        ORDER BY site, channel, sampled_at DESC
        """
    )
    return [dict(row) for row in rows]


async def list_transcripts(pool: PoolLike, limit: int = 100, raw_header: str | None = None) -> list[dict]:
    """Filtering by `raw_header` is how the UI attaches transcripts to an
    alert: the SAME header is the only identifier shared between
    `fusion`'s alert (via its RF source) and `stt_worker`'s transcript,
    which never sees an alert id at all."""
    if raw_header:
        rows = await pool.fetch(
            "SELECT * FROM transcripts WHERE raw_header = $1 ORDER BY timestamp_ns DESC LIMIT $2",
            raw_header,
            limit,
        )
    else:
        rows = await pool.fetch("SELECT * FROM transcripts ORDER BY timestamp_ns DESC LIMIT $1", limit)
    return [dict(row) for row in rows]


async def list_dispatches(pool: PoolLike, limit: int = 100, raw_header: str | None = None) -> list[dict]:
    if raw_header:
        rows = await pool.fetch(
            "SELECT * FROM dispatches WHERE raw_header = $1 ORDER BY dispatched_at DESC LIMIT $2",
            raw_header,
            limit,
        )
    else:
        rows = await pool.fetch("SELECT * FROM dispatches ORDER BY dispatched_at DESC LIMIT $1", limit)
    return [dict(row) for row in rows]


async def health_history(pool: PoolLike, since_seconds: int = 3600, buckets: int = 60) -> list[dict]:
    """Down-sampled RF health per (site, channel) for the UI's sparklines.

    Aggregated in Postgres rather than shipping raw samples: `sdr_rx`
    writes health continuously per channel, so an hour is thousands of
    rows per channel and the sparkline can only draw about sixty pixels
    of them anyway. `dead` is maxed rather than averaged over the bucket --
    a channel that was dead for part of a bucket must render as dead, not
    as a fraction that rounds away."""
    rows = await pool.fetch(
        """
        SELECT site,
               channel,
               time_bucket(make_interval(secs => $2::double precision), sampled_at) AS bucket,
               AVG(rms) AS rms,
               AVG(power) AS power,
               BOOL_OR(dead) AS dead
        FROM health_samples
        WHERE sampled_at > NOW() - make_interval(secs => $1::double precision)
        GROUP BY site, channel, bucket
        ORDER BY site, channel, bucket
        """,
        float(since_seconds),
        float(since_seconds) / max(1, buckets),
    )
    return [dict(row) for row in rows]


async def alert_state_counts(pool: PoolLike) -> dict[str, int]:
    """Feeds the `RF_ONLY`/`API_ONLY` divergence rate -- design doc §5:
    "The RF_ONLY/API_ONLY divergence rate over time is the best single
    health metric for the whole system." """
    rows = await pool.fetch("SELECT state, COUNT(*) AS count FROM alerts GROUP BY state")
    return {row["state"]: row["count"] for row in rows}


async def dispatch_summary(pool: PoolLike, since_seconds: int = 86_400) -> dict:
    """Sent-vs-skipped counts over a recent window, for the status bar.

    Pairs with the divergence rate as a health metric but answers a
    different question: divergence says whether RF and the API agree,
    this says whether anything Tocsin decided to send actually left the
    building. A system with a perfect divergence rate and an unplugged
    Meshtastic node looks healthy by every other number on the page."""
    rows = await pool.fetch(
        """
        SELECT sent, reason, COUNT(*) AS count
        FROM dispatches
        WHERE dispatched_at > NOW() - make_interval(secs => $1::double precision)
        GROUP BY sent, reason
        """,
        float(since_seconds),
    )
    sent = sum(row["count"] for row in rows if row["sent"])
    skipped = sum(row["count"] for row in rows if not row["sent"])
    by_reason: dict[str, int] = {}
    for row in rows:
        by_reason[row["reason"]] = by_reason.get(row["reason"], 0) + row["count"]
    return {"sent": sent, "skipped": skipped, "by_reason": by_reason, "since_seconds": since_seconds}
