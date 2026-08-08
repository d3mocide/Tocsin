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


async def alert_state_counts(pool: PoolLike) -> dict[str, int]:
    """Feeds the `RF_ONLY`/`API_ONLY` divergence rate -- design doc §5:
    "The RF_ONLY/API_ONLY divergence rate over time is the best single
    health metric for the whole system." """
    rows = await pool.fetch("SELECT state, COUNT(*) AS count FROM alerts GROUP BY state")
    return {row["state"]: row["count"] for row in rows}
