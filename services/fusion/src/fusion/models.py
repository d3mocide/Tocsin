"""Canonical types for fusion's correlation and alert-store logic (design
doc §5).

`SameEventIn`/`CapAlertIn` duplicate the wire shape `same_decoder` and
`nws_poller` publish to Redis Streams (service boundary, CLAUDE.md -- no
cross-service imports) rather than reaching into either package, the same
way `same_decoder.subscriber` duplicates `sdr_rx.bus`'s ZMQ wire format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


@dataclass(frozen=True)
class SameEventIn:
    site: str
    channel: str
    # Decode-time UTC timestamp, standing in for SAME's own issue time --
    # see correlator.py's docstring for why.
    received_at: datetime
    event_code: str
    event_name: str
    tier: str
    fips_codes: tuple[str, ...]
    originator: str
    callsign: str
    purge_minutes: int
    raw_header: str


@dataclass(frozen=True)
class KeywordEventIn:
    """Wire shape of `stt_worker.service.KeywordEvent` (design doc's
    live-transcription addendum to §5): a hazard phrase matched in a
    *continuously*-transcribed chunk of ordinary NWR narration, never a
    SAME header. No FIPS codes at all -- unlike a decoded SAME header,
    freeform speech carries no reliable county-level geography, so
    correlation against CAP by area isn't attempted for this source (see
    `store.ingest_keyword`'s own docstring)."""

    site: str
    channel: str
    received_at: datetime
    event_code: str
    event_name: str
    tier: str
    matched_phrase: str
    transcript_text: str


@dataclass(frozen=True)
class CapAlertIn:
    id: str
    event: str
    headline: str | None
    status: str
    message_type: str
    category: str
    severity: str
    certainty: str
    urgency: str
    area_desc: str
    sent: datetime
    effective: datetime | None
    onset: datetime | None
    expires: datetime | None
    ends: datetime | None
    same_codes: tuple[str, ...]
    ugc_codes: tuple[str, ...]
    vtec: str | None


class AlertState(str, Enum):
    RF_ONLY = "RF_ONLY"
    API_ONLY = "API_ONLY"
    CONFIRMED = "CONFIRMED"
    # A keyword hit in continuously-transcribed audio, with no SAME header
    # and no CAP match -- the design doc's live-transcription addendum to
    # §5. Deliberately its own state, not folded into RF_ONLY: RF_ONLY
    # means a deterministic SAME header decode, and dispatcher's stage 1
    # (design doc §7) fires off that guarantee. A fuzzy keyword match in a
    # Whisper transcript must never carry that same guarantee -- see
    # `store.ingest_keyword`'s docstring and dispatcher's own
    # `parse_rf_source` (no RF source here, so stage 1 never even sees it).
    TRANSCRIPT_ONLY = "TRANSCRIPT_ONLY"


@dataclass(frozen=True)
class RFSource:
    event: SameEventIn
    kind: str = field(default="RF", init=False)


@dataclass(frozen=True)
class ApiSource:
    alert: CapAlertIn
    kind: str = field(default="API", init=False)


@dataclass(frozen=True)
class TranscriptSource:
    # Named `keyword_event`, not `event` -- the frontend's `AlertSource`
    # type (web/src/types.ts) already uses `event` for `RFSource`'s
    # `SameEvent` payload; a same-named field with a different shape here
    # would either collide or force callers to narrow a widened union
    # before touching it. Distinct names sidestep both.
    keyword_event: KeywordEventIn
    kind: str = field(default="TRANSCRIPT", init=False)


AlertSource = RFSource | ApiSource | TranscriptSource


@dataclass
class Alert:
    """One canonical alert with provenance -- never a merged blob (design
    doc §5): `sources` grows from one entry to two on confirmation, it
    never collapses into a single flattened record."""

    id: str
    state: AlertState
    confidence: float
    event_name: str
    fips_codes: tuple[str, ...]
    first_seen: datetime
    last_updated: datetime
    sources: tuple[AlertSource, ...]
