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


@dataclass(frozen=True)
class RFSource:
    event: SameEventIn
    kind: str = field(default="RF", init=False)


@dataclass(frozen=True)
class ApiSource:
    alert: CapAlertIn
    kind: str = field(default="API", init=False)


AlertSource = RFSource | ApiSource


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
