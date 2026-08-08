"""Redis-persisted idempotency so a dispatcher restart doesn't re-send an
alert it already dispatched (design doc §7, roadmap.md Phase 6's exit
criteria).

SAME carries no ETN (design doc §5's own note, echoed in
`fusion.correlator`) -- the design doc's example key tuple
`(event, fips_set, etn, stage)` substitutes each SAME event's own
`raw_header` for the ETN slot: it already uniquely encodes event code,
FIPS set, purge offset, issue time, and callsign as one string (design doc
§4's `ZCZC` format), so hashing it plus `stage` is equivalent to
reconstructing that tuple by hand, with no new plumbing through
`same_decoder`/`fusion` needed to carry a separate ID through.
"""

from __future__ import annotations

import hashlib

KEY_PREFIX = "tocsin:dispatch:sent"
DEFAULT_TTL_SECONDS = 24 * 60 * 60  # generous: purge windows are hours, not days


def idempotency_key(raw_header: str, stage: str) -> str:
    digest = hashlib.sha256(f"{stage}:{raw_header}".encode()).hexdigest()[:32]
    return f"{KEY_PREFIX}:{digest}"


class IdempotencyStore:
    def __init__(self, redis_client, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    def claim(self, raw_header: str, stage: str) -> bool:
        """Atomically claims `(raw_header, stage)`. Returns `True` the
        first time -- proceed with dispatch. Returns `False` on every
        subsequent call, this run or after a future restart -- already
        sent, skip. Callers must only call this immediately before
        actually attempting the send (see `service.py`): claiming first
        and then deciding not to send for some other reason would
        permanently strand a real alert as "already sent" when it never
        went out."""
        key = idempotency_key(raw_header, stage)
        return bool(self._redis.set(key, "1", nx=True, ex=self._ttl_seconds))
