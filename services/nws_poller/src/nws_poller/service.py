"""Wires the NWS alerts client, per-request-target ETag tracking, a single
shared dedup tracker, and sink into one polling pipeline (design doc §5,
§10 milestone 5)."""

from __future__ import annotations

from .client import NwsAlertsClient
from .parser import parse_feature
from .redis_sink import CapAlertSink, LoggingCapAlertSink
from .tracker import SeenAlertTracker

import math

EARTH_RADIUS_MILES = 3958.756

def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_MILES * c

KNOWN_CENTROIDS: dict[str, tuple[float, float]] = {
    # Oregon Zones
    "ORZ108": (45.87, -122.85),
    "ORZ109": (45.52, -122.98),
    "ORZ110": (45.46, -122.84),
    "ORZ111": (45.52, -122.65),
    "ORZ112": (45.52, -122.45),
    "ORZ113": (45.38, -122.52),
    "ORZ114": (45.10, -123.20),
    "ORZ115": (44.95, -122.95),
    "ORZ116": (44.56, -123.26),
    "ORZ117": (44.63, -123.10),
    "ORZ118": (44.05, -123.08),
    "ORZ119": (45.58, -122.18),
    "ORZ120": (45.60, -122.10),
    "ORZ123": (45.30, -122.25),
    # Washington Zones
    "WAZ204": (46.18, -122.90),
    "WAZ205": (45.82, -122.58),
    "WAZ206": (45.65, -122.62),
    "WAZ207": (45.62, -122.40),
    "WAZ208": (45.90, -122.25),
    "WAZ209": (45.65, -121.98),
    # FIPS Counties
    "041051": (45.52, -122.65),
    "041067": (45.52, -122.98),
    "041005": (45.30, -122.25),
    "041009": (45.87, -122.85),
    "041071": (45.10, -123.20),
    "041047": (44.95, -122.95),
    "041053": (44.95, -123.20),
    "041003": (44.56, -123.26),
    "041043": (44.63, -123.10),
    "041039": (44.05, -123.08),
    "53011": (45.65, -122.62),
    "53015": (46.18, -122.90),
    "53059": (45.90, -122.25),
}

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
        max_radius_miles: float | None = None,
        operator_lat: float | None = None,
        operator_lon: float | None = None,
    ):
        self._client = client
        self._areas = areas or []
        self._zones = zones or []
        self._strict_zone_filter = strict_zone_filter
        self._max_radius_miles = max_radius_miles
        self._operator_lat = operator_lat
        self._operator_lon = operator_lon
        self._sink = sink or LoggingCapAlertSink()
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
        if self._max_radius_miles is not None and self._operator_lat is not None and self._operator_lon is not None:
            filtered = []
            for alert in alerts:
                codes = list(alert.ugc_codes) + list(alert.same_codes)
                min_dist = float("inf")
                for code in codes:
                    if code in KNOWN_CENTROIDS:
                        c_lat, c_lon = KNOWN_CENTROIDS[code]
                        dist = haversine_miles(self._operator_lat, self._operator_lon, c_lat, c_lon)
                        if dist < min_dist:
                            min_dist = dist
                if min_dist <= self._max_radius_miles or min_dist == float("inf"):
                    filtered.append(alert)
            alerts = tuple(filtered)
        fresh = self._tracker.filter_new_or_updated(alerts)
        for alert in fresh:
            self._sink.record(alert)
        return len(fresh)

