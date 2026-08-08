"""Wires the NWS alerts client, per-area ETag tracking, dedup tracker, and
sink into one polling pipeline (design doc §5, §10 milestone 5)."""

from __future__ import annotations

from .client import NwsAlertsClient
from .parser import parse_feature
from .redis_sink import CapAlertSink, LoggingCapAlertSink
from .tracker import SeenAlertTracker


class Poller:
    def __init__(self, client: NwsAlertsClient, areas: list[str], sink: CapAlertSink | None = None):
        self._client = client
        self._areas = areas
        self._sink = sink or LoggingCapAlertSink()
        self._etags: dict[str, str] = {}
        self._trackers: dict[str, SeenAlertTracker] = {area: SeenAlertTracker() for area in areas}

    def poll_once(self) -> int:
        """Polls every configured area once; returns the number of new/updated
        alerts emitted this cycle."""
        return sum(self._poll_area(area) for area in self._areas)

    def _poll_area(self, area: str) -> int:
        result = self._client.fetch(area, etag=self._etags.get(area))
        if result.not_modified:
            return 0
        if result.etag:
            self._etags[area] = result.etag
        alerts = tuple(parse_feature(feature) for feature in result.features)
        fresh = self._trackers[area].filter_new_or_updated(alerts)
        for alert in fresh:
            self._sink.record(alert)
        return len(fresh)
