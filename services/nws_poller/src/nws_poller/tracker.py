"""Tracks which CAP alerts have already been emitted, keyed on `(id, sent)`.

`/alerts/active` returns the full current snapshot of active alerts on
every successful (non-304) call, not a delta -- without this, every
currently-active alert would be re-emitted to `fusion` on every single poll
for as long as it stays active, not just when it's new or changed. A
changed `sent` timestamp is CAP's own signal that NWS reissued the
product (update/correction), which is exactly the case that should still
get re-emitted.

When a Redis client is provided, the seen set is persisted in a hash key
so container restarts don't re-emit every currently-active alert.
"""

from __future__ import annotations

from .parser import CapAlert

REDIS_KEY = "tocsin:nws_poller:seen"


class SeenAlertTracker:
    def __init__(self, redis_client=None):
        self._redis = redis_client
        self._last_sent: dict[str, str] = {}
        if self._redis is not None:
            stored = self._redis.hgetall(REDIS_KEY)
            if stored:
                self._last_sent.update(stored)

    def filter_new_or_updated(self, alerts: tuple[CapAlert, ...]) -> list[CapAlert]:
        fresh = []
        for alert in alerts:
            sent_key = alert.sent.isoformat()
            if self._last_sent.get(alert.id) != sent_key:
                fresh.append(alert)
                self._last_sent[alert.id] = sent_key
                if self._redis is not None:
                    self._redis.hset(REDIS_KEY, alert.id, sent_key)
        return fresh
