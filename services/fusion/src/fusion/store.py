"""In-memory correlation state machine (design doc §5): ingest one SAME
event or CAP alert at a time, match it against currently open alerts, and
emit a canonical `Alert` with `sources[]` -- never a merged blob.

Linear scan over open alerts is deliberate, not a placeholder: even a busy
severe-weather evening produces a handful of concurrently open alerts, not
thousands, so there's no correctness or performance reason to reach for an
index before one is actually needed (CLAUDE.md: don't build abstractions
ahead of the problem that needs them).

Not handled yet, deliberately out of this phase's scope: a second SAME
event or CAP update arriving for an already-`CONFIRMED` alert (e.g. a CAP
"Update" reissue, or two sites hearing the same broadcast) opens a *new*
Alert rather than attaching to the existing one -- the design doc's stated
correlation key is SAME<->CAP only, and multi-site RF-RF or CAP-update
correlation isn't part of it. Worth revisiting once real traffic shows how
often it matters.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Protocol

from .confidence import compute_confidence
from .correlator import DEFAULT_TIME_TOLERANCE, matches
from .mapping import EventMapping
from .models import Alert, AlertSource, AlertState, ApiSource, CapAlertIn, RFSource, SameEventIn
from .serialize import alert_to_json


class AlertSink(Protocol):
    def record(self, alert: Alert) -> None: ...


class LoggingAlertSink:
    """Default sink: one JSON line per alert (creation or state
    transition) on stdout. No TimescaleDB alert-store consumer exists yet
    (that's Phase 8's `api` service) -- same seam pattern as every other
    service's `LoggingXSink`."""

    def record(self, alert: Alert) -> None:
        print(alert_to_json(alert), flush=True)


class AlertStore:
    def __init__(
        self,
        mapping: EventMapping,
        mode: str,
        sink: AlertSink | None = None,
        time_tolerance: timedelta = DEFAULT_TIME_TOLERANCE,
    ):
        self._mapping = mapping
        self._mode = mode
        self._sink = sink or LoggingAlertSink()
        self._tolerance = time_tolerance
        self._open_rf_only: list[Alert] = []
        self._open_api_only: list[Alert] = []
        self._all: list[Alert] = []

    @property
    def open_alerts(self) -> tuple[Alert, ...]:
        """Alerts still eligible for confirmation -- `RF_ONLY`/`API_ONLY`
        only. Once `CONFIRMED`, an alert leaves this set (see `_confirm`)
        but stays in `all_alerts`."""
        return tuple(self._open_rf_only) + tuple(self._open_api_only)

    @property
    def all_alerts(self) -> tuple[Alert, ...]:
        return tuple(self._all)

    def ingest_same(self, event: SameEventIn) -> Alert:
        for alert in self._open_rf_only:
            existing_rf = _rf_source_of(alert).event
            if existing_rf.raw_header == event.raw_header or (
                existing_rf.callsign == event.callsign
                and existing_rf.event_code == event.event_code
                and existing_rf.fips_codes == event.fips_codes
            ):
                alert.last_updated = event.received_at
                alert.sources = (RFSource(event),)
                self._sink.record(alert)
                return alert

        for alert in self._open_api_only:
            cap = _cap_source_of(alert).alert
            if matches(event, cap, self._mapping, self._tolerance):
                self._open_api_only.remove(alert)
                self._confirm(alert, RFSource(event), event.received_at)
                return alert

        alert = Alert(
            id=uuid.uuid4().hex,
            state=AlertState.RF_ONLY,
            confidence=compute_confidence(AlertState.RF_ONLY, self._mode),
            event_name=event.event_name,
            fips_codes=event.fips_codes,
            first_seen=event.received_at,
            last_updated=event.received_at,
            sources=(RFSource(event),),
        )
        self._open_rf_only.append(alert)
        self._all.append(alert)
        self._sink.record(alert)
        return alert

    def ingest_cap(self, cap: CapAlertIn) -> Alert:
        for alert in self._open_api_only:
            existing_cap = _cap_source_of(alert).alert
            if existing_cap.id == cap.id:
                alert.last_updated = cap.sent
                alert.sources = (ApiSource(cap),)
                self._sink.record(alert)
                return alert

        for alert in self._open_rf_only:
            same = _rf_source_of(alert).event
            if matches(same, cap, self._mapping, self._tolerance):
                self._open_rf_only.remove(alert)
                self._confirm(alert, ApiSource(cap), cap.sent)
                return alert

        alert = Alert(
            id=hashlib.sha256(cap.id.encode()).hexdigest()[:32],
            state=AlertState.API_ONLY,
            confidence=compute_confidence(AlertState.API_ONLY, self._mode),
            event_name=cap.event,
            fips_codes=cap.same_codes,
            first_seen=cap.sent,
            last_updated=cap.sent,
            sources=(ApiSource(cap),),
        )
        self._open_api_only.append(alert)
        self._all.append(alert)
        self._sink.record(alert)
        return alert

    def _confirm(self, alert: Alert, new_source: AlertSource, observed_at: datetime) -> None:
        alert.state = AlertState.CONFIRMED
        alert.confidence = compute_confidence(AlertState.CONFIRMED, self._mode)
        alert.sources = alert.sources + (new_source,)
        alert.last_updated = observed_at
        self._sink.record(alert)


def _rf_source_of(alert: Alert) -> RFSource:
    source = alert.sources[0]
    assert isinstance(source, RFSource)
    return source


def _cap_source_of(alert: Alert) -> ApiSource:
    source = alert.sources[0]
    assert isinstance(source, ApiSource)
    return source
