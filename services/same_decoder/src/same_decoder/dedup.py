"""Collapses repeated SAME header transmissions into one event.

Keyed on parsed fields rather than the raw string, so a difference outside
the fields we care about doesn't create a spurious duplicate. A short TTL
(not "for the life of the process") because the same event code can
legitimately recur later -- a new tornado warning for the same counties an
hour after the last one expired must not be swallowed as a duplicate.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Hashable

if TYPE_CHECKING:
    from .parser import SameHeader

DEFAULT_TTL_SECONDS = 60.0


def _dedup_key(header: "SameHeader") -> Hashable:
    return (
        header.originator,
        header.event_code,
        header.fips_codes,
        header.purge_code,
        header.issue_day_of_year,
        header.issue_hour,
        header.issue_minute,
        header.callsign,
    )


class HeaderDeduplicator:
    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._seen: dict[Hashable, float] = {}

    def is_duplicate(self, header: "SameHeader", now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self._expire(now)
        key = _dedup_key(header)
        if key in self._seen:
            return True
        self._seen[key] = now
        return False

    def _expire(self, now: float) -> None:
        expired = [k for k, seen_at in self._seen.items() if now - seen_at > self._ttl]
        for k in expired:
            del self._seen[k]
