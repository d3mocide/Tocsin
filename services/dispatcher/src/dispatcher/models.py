"""Duplicates the wire shape `fusion` publishes to `tocsin:alerts`
(service boundary, CLAUDE.md) -- specifically just enough to build a
stage-1 message: the RF source's own SAME-header fields. An alert with no
RF source (pure `API_ONLY`) has nothing for stage 1 to fire on -- design
doc §7: stage 1 fires "on SAME header decode," never from a CAP-only
alert.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RFAlertIn:
    alert_id: str
    event_code: str
    tier: str
    fips_codes: tuple[str, ...]
    purge_minutes: int
    received_at: datetime
    raw_header: str


def parse_rf_source(payload: dict) -> RFAlertIn | None:
    for source in payload.get("sources", []):
        if source.get("kind") == "RF":
            event = source["event"]
            return RFAlertIn(
                alert_id=payload["id"],
                event_code=event["event_code"],
                tier=event["tier"],
                fips_codes=tuple(event["fips_codes"]),
                purge_minutes=event["purge_minutes"],
                received_at=datetime.fromisoformat(event["received_at"]),
                raw_header=event["raw_header"],
            )
    return None
