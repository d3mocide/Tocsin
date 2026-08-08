"""Duplicates the wire shapes `fusion` publishes to `tocsin:alerts` and
`stt_worker` publishes to `tocsin:transcripts` (service boundary,
CLAUDE.md) -- specifically just enough of each to run stage 1 and stage 2.

`RFAlertIn` covers stage 1: the RF source's own SAME-header fields. An
alert with no RF source (pure `API_ONLY`) has nothing for stage 1 to fire
on -- design doc §7: stage 1 fires "on SAME header decode," never from a
CAP-only alert.

`TranscriptIn` covers stage 2: `stt_worker`'s `GuardedTranscript` already
carries `tier` and `raw_header` (threaded through from `segment_capture`'s
own independent SAME-header parse -- Phase 7), so stage 2 needs no
separate tier lookup of its own to gate on Tier A.
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


@dataclass(frozen=True)
class TranscriptIn:
    site: str
    channel: str
    event_code: str
    tier: str
    fips_codes: tuple[str, ...]
    raw_header: str
    text: str
    passed_guard: bool
    guard_reason: str | None


def parse_transcript(payload: dict) -> TranscriptIn:
    return TranscriptIn(
        site=payload["site"],
        channel=payload["channel"],
        event_code=payload["event_code"],
        tier=payload["tier"],
        fips_codes=tuple(payload["fips_codes"]),
        raw_header=payload["raw_header"],
        text=payload["text"],
        passed_guard=payload["passed_guard"],
        guard_reason=payload.get("guard_reason"),
    )
