"""Collapses near-duplicate alerts before they consume a mesh token
(design doc §7's airtime budget: "Dedup on (event, fips, etn)"). SAME
carries no ETN (see `idempotency.py`'s docstring for the same
substitution reasoning) -- keyed on `(event_code, fips_codes)` instead.

This is a *second*, shorter-window line of defense on top of
`idempotency.py`'s exact-resend guard: it catches near-duplicates that
guard wouldn't, e.g. two sites' dongles both hearing the same real-world
broadcast and producing two distinct fusion `Alert`s for one real event
(`fusion/store.py`'s own docstring names multi-site RF-RF correlation as
an explicitly out-of-scope gap upstream of this). Same TTL-eviction shape
as `same_decoder.dedup.HeaderDeduplicator`.
"""

from __future__ import annotations

import time

DEFAULT_TTL_SECONDS = 300.0  # matches fusion's own correlation time-window tolerance


class AlertDeduplicator:
    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._seen: dict[tuple[str, tuple[str, ...]], float] = {}

    def is_duplicate(self, event_code: str, fips_codes: tuple[str, ...], now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self._expire(now)
        key = (event_code, fips_codes)
        if key in self._seen:
            return True
        self._seen[key] = now
        return False

    def _expire(self, now: float) -> None:
        expired = [k for k, seen_at in self._seen.items() if now - seen_at > self._ttl]
        for k in expired:
            del self._seen[k]
