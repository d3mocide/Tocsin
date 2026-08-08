"""Tracks which CAP alerts have already been emitted, keyed on `(id, sent)`.

`/alerts/active` returns the full current snapshot of active alerts on
every successful (non-304) call, not a delta -- without this, every
currently-active alert would be re-emitted to `fusion` on every single poll
for as long as it stays active, not just when it's new or changed. A
changed `sent` timestamp is CAP's own signal that NWS reissued the
product (update/correction), which is exactly the case that should still
get re-emitted.
"""

from __future__ import annotations

from .parser import CapAlert


class SeenAlertTracker:
    def __init__(self):
        self._last_sent: dict[str, str] = {}

    def filter_new_or_updated(self, alerts: tuple[CapAlert, ...]) -> list[CapAlert]:
        fresh = []
        for alert in alerts:
            sent_key = alert.sent.isoformat()
            if self._last_sent.get(alert.id) != sent_key:
                fresh.append(alert)
                self._last_sent[alert.id] = sent_key
        return fresh
