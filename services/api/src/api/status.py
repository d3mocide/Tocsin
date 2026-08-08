"""Reads the per-service liveness heartbeats (`tocsin:status:<service>`,
written by each service's own `heartbeat.py`) and reports them against the
set of services a deployment in this mode is *expected* to be running.

The expected-set comparison is the whole point. A crashed service writes
nothing, so listing only the keys that exist would render a dead
`dispatcher` as simply absent from the table -- indistinguishable from a
healthy one on a quiet night, and exactly the failure this endpoint exists
to catch. `EXPECTED_*` below is therefore a checked-in list, not something
derived from what happens to be in Redis.

Mode matters: `nws_poller` only runs under `TOCSIN_MODE=hybrid` (design
doc §8's connectivity contract), so reporting it "down" under `offgrid`
would be a permanent false alarm on precisely the deployment that must
work without a network at all.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

KEY_PREFIX = "tocsin:status"

EXPECTED_ALWAYS = (
    "sdr_rx",
    "same_decoder",
    "live_audio",
    "segment_capture",
    "stt_worker",
    "fusion",
    "dispatcher",
    "api",
)
EXPECTED_HYBRID_ONLY = ("nws_poller",)

HYBRID_MODE = "hybrid"

STATUS_UP = "up"
STATUS_DOWN = "down"
# Reported but not in any expected list -- a service someone added without
# updating EXPECTED_ALWAYS, or a stale key from a renamed one. Shown
# rather than hidden: an unexplained row is a prompt to fix this list.
STATUS_UNEXPECTED = "unexpected"


def expected_services(mode: str | None) -> tuple[str, ...]:
    if (mode or "").lower() == HYBRID_MODE:
        return EXPECTED_ALWAYS + EXPECTED_HYBRID_ONLY
    return EXPECTED_ALWAYS


async def read_heartbeats(redis_client) -> dict[str, dict]:
    keys = await redis_client.keys(f"{KEY_PREFIX}:*")
    if not keys:
        return {}
    prefix_len = len(KEY_PREFIX) + 1
    heartbeats: dict[str, dict] = {}
    for key in keys:
        raw = await redis_client.get(key)
        if raw is None:
            # Expired between KEYS and GET -- a normal race at a 30s TTL,
            # not an error: the service is simply late, and the next poll
            # will report it as down if it stays gone.
            continue
        try:
            heartbeats[key[prefix_len:]] = json.loads(raw)
        except ValueError:
            continue
    return heartbeats


async def list_services(redis_client, mode: str | None = None) -> list[dict]:
    heartbeats = await read_heartbeats(redis_client)
    expected = expected_services(mode)
    now = datetime.now(timezone.utc)

    rows = []
    for service in expected:
        beat = heartbeats.get(service)
        rows.append(_row(service, beat, now, expected=True))
    for service in sorted(set(heartbeats) - set(expected)):
        rows.append(_row(service, heartbeats[service], now, expected=False))
    return rows


def _row(service: str, beat: dict | None, now: datetime, expected: bool) -> dict:
    if beat is None:
        return {
            "service": service,
            "status": STATUS_DOWN,
            "expected": expected,
            "updated_at": None,
            "age_seconds": None,
            "detail": {},
        }
    return {
        "service": service,
        "status": STATUS_UP if expected else STATUS_UNEXPECTED,
        "expected": expected,
        "updated_at": beat.get("updated_at"),
        "age_seconds": _age_seconds(beat.get("updated_at"), now),
        "detail": beat.get("detail") or {},
    }


def _age_seconds(updated_at: str | None, now: datetime) -> float | None:
    if not updated_at:
        return None
    try:
        parsed = datetime.fromisoformat(updated_at)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - parsed).total_seconds())
