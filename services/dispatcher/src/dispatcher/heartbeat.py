"""Liveness heartbeat: dispatcher SETEXes `tocsin:status:dispatcher` from its
main loop so `api`'s `GET /services` can tell "running" from "not running".

The TTL is the entire mechanism -- absence of the key means the process is
gone, so a dead service cannot look healthy by leaving stale state behind.
That is why this exists at all rather than deriving liveness from "has
this service produced data recently": on a quiet night with no alerts, a
crashed dispatcher and a working one produce identical output, and a status
board that cannot tell those apart is worse than none.

Deliberately duplicated per service instead of shared (CLAUDE.md: services
communicate over Redis/ZMQ/MQTT, not Python imports). `beat()` is called
unconditionally from the main loop and throttles itself, so callers don't
need their own timer, and it never raises -- a Redis blip must not take
down the process whose liveness it reports.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

SERVICE_NAME = "dispatcher"
KEY_PREFIX = "tocsin:status"
# TTL is 3x the write interval: one missed write (a slow poll cycle, a
# brief Redis hiccup) must not flap the service to "down" on the status
# board, but a genuinely dead process still disappears within 30s.
DEFAULT_INTERVAL_SECONDS = 10.0
DEFAULT_TTL_SECONDS = 30


class Heartbeat:
    def __init__(
        self,
        redis_client,
        service: str = SERVICE_NAME,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        clock=time.monotonic,
    ):
        self._redis = redis_client
        self._service = service
        self._interval = interval_seconds
        self._ttl = ttl_seconds
        self._clock = clock
        self._last_write: float | None = None

    @property
    def key(self) -> str:
        return f"{KEY_PREFIX}:{self._service}"

    def beat(self, **detail) -> bool:
        """Writes the heartbeat if `interval_seconds` has elapsed since the
        last one. Returns whether a write actually happened -- for tests;
        callers in a main loop ignore it."""
        now = self._clock()
        if self._last_write is not None and (now - self._last_write) < self._interval:
            return False
        self._last_write = now
        payload = {
            "service": self._service,
            "mode": os.environ.get("TOCSIN_MODE"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "ttl_seconds": self._ttl,
            "detail": detail,
        }
        try:
            self._redis.setex(self.key, self._ttl, json.dumps(payload))
        except Exception as exc:
            # Never fatal: this reports liveness, it does not provide it.
            print(f"dispatcher: heartbeat write failed: {exc}", file=sys.stderr)
            return False
        return True


def build(redis_client, service: str = SERVICE_NAME) -> Heartbeat | None:
    """`None` when there's no Redis client configured -- same optional-sink
    seam every service already uses for its Redis publisher, so a local run
    without Redis stays exactly as runnable as it was."""
    if redis_client is None:
        return None
    return Heartbeat(redis_client, service=service)
