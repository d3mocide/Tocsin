"""Wires the NWS alerts client, per-request-target ETag tracking, a single
shared dedup tracker, and sink into one polling pipeline (design doc §5,
§10 milestone 5)."""

from __future__ import annotations

from .client import NwsAlertsClient
from .parser import parse_feature
from .redis_sink import CapAlertSink, LoggingCapAlertSink
from .tracker import SeenAlertTracker

# Not a real area code -- `_etags` is keyed by area already, so the combined
# zone-list request needs its own key in the same dict rather than a second
# parallel structure. `NWS_POLLER_AREAS` values are always uppercase 2-4
# letter state/marine codes, so this can't collide with one.
_ZONES_KEY = "__zones__"


class Poller:
    def __init__(
        self,
        client: NwsAlertsClient,
        areas: list[str] | None = None,
        sink: CapAlertSink | None = None,
        zones: list[str] | None = None,
        strict_zone_filter: bool = False,
    ):
        self._client = client
        self._areas = areas or []
        self._zones = zones or []
        self._strict_zone_filter = strict_zone_filter
        self._sink = sink or LoggingCapAlertSink()
        # ETags are conditional-GET state and must stay per request target
        # (each area, plus the combined zone request, is its own HTTP call
        # with its own Last-Modified-equivalent). The dedup tracker below is
        # different: it decides what's *new*, and `NWS_POLLER_ZONES` is
        # explicitly a narrower filter layered on top of `NWS_POLLER_AREAS`
        # (README), so the same CAP alert routinely appears in both an
        # area's response and the zone response -- and, pre-existing, can
        # already appear in two overlapping areas (a marine warning under
        # both `OR` and `WA`). One shared tracker, keyed on the CAP alert's
        # own `id` regardless of which request surfaced it, means `fusion`
        # (which has no id-based dedup of its own -- see `store.py`'s
        # `ingest_cap`, one new `Alert` per call that doesn't match an open
        # RF-only alert) only ever sees a given alert once per real
        # new-or-updated occurrence, not once per overlapping request that
        # happened to return it.
        self._etags: dict[str, str] = {}
        self._tracker = SeenAlertTracker()

    def poll_once(self) -> int:
        """Polls every configured area once (if any), plus one combined
        request for `zones` if configured; returns the number of
        new/updated alerts emitted this cycle."""
        total = sum(self._poll_area(area) for area in self._areas)
        if self._zones:
            total += self._poll_zones()
        return total

    def _poll_area(self, area: str) -> int:
        result = self._client.fetch(area, etag=self._etags.get(area))
        return self._emit_fresh(area, result)

    def _poll_zones(self) -> int:
        result = self._client.fetch_zones(self._zones, etag=self._etags.get(_ZONES_KEY))
        return self._emit_fresh(_ZONES_KEY, result)

    def _emit_fresh(self, etag_key: str, result) -> int:
        if result.not_modified:
            return 0
        if result.etag:
            self._etags[etag_key] = result.etag
        alerts = tuple(parse_feature(feature) for feature in result.features)
        if self._strict_zone_filter and self._zones:
            target_set = set(self._zones)
            alerts = tuple(
                alert
                for alert in alerts
                if any(code in target_set for code in alert.ugc_codes)
                or any(code in target_set for code in alert.same_codes)
            )
        fresh = self._tracker.filter_new_or_updated(alerts)
        for alert in fresh:
            self._sink.record(alert)
        return len(fresh)

