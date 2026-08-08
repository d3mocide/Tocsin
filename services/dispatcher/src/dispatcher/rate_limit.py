"""Token-bucket rate limiter for mesh airtime (design doc §7: "~6 msgs/hour
sustained, burst 3" -- "without this, one active convective evening
saturates the mesh for every user on it").

In-process, not Redis-backed: `dispatcher` is architecturally a singleton
(mirrors `fusion`'s in-memory `AlertStore`, `sdr-rx`'s "one process owns
the dongle" pattern), and a restart resetting the bucket to full is a
soft QoS concern, not a correctness one -- unlike `idempotency.py`,
nothing here is required to survive a restart.
"""

from __future__ import annotations

import time

DEFAULT_CAPACITY = 3
DEFAULT_REFILL_PER_HOUR = 6.0


class TokenBucket:
    def __init__(
        self,
        capacity: int = DEFAULT_CAPACITY,
        refill_per_hour: float = DEFAULT_REFILL_PER_HOUR,
        now: float | None = None,
    ):
        self._capacity = capacity
        self._refill_per_second = refill_per_hour / 3600.0
        self._tokens = float(capacity)
        self._last_refill = now if now is not None else time.monotonic()

    def try_acquire(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        elapsed = max(0.0, now - self._last_refill)
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_per_second)
        self._last_refill = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False
