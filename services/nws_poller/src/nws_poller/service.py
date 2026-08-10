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
    # Oregon FIPS Counties (041xxx)
    "041001": (44.71, -117.67), # Baker
    "041003": (44.49, -123.43), # Benton
    "041005": (45.30, -122.25), # Clackamas
    "041007": (45.98, -123.71), # Clatsop
    "041009": (45.87, -122.85), # Columbia
    "041011": (43.19, -124.08), # Coos
    "041013": (44.14, -120.36), # Crook
    "041015": (42.46, -124.16), # Curry
    "041017": (43.91, -121.23), # Deschutes
    "041019": (43.29, -123.18), # Douglas
    "041021": (45.37, -120.21), # Gilliam
    "041023": (44.43, -119.00), # Grant
    "041025": (43.20, -118.97), # Harney
    "041027": (45.52, -121.65), # Hood River
    "041029": (42.42, -122.78), # Jackson
    "041031": (44.62, -121.32), # Jefferson
    "041033": (42.36, -123.56), # Josephine
    "041035": (42.40, -121.75), # Klamath
    "041037": (42.50, -120.30), # Lake
    "041039": (44.05, -123.08), # Lane
    "041041": (44.64, -123.91), # Lincoln
    "041043": (44.48, -122.53), # Linn
    "041045": (43.20, -117.62), # Malheur
    "041047": (44.90, -122.81), # Marion
    "041049": (45.42, -119.58), # Morrow
    "041051": (45.52, -122.65), # Multnomah
    "041053": (44.90, -123.40), # Polk
    "041055": (45.42, -120.68), # Sherman
    "041057": (45.46, -123.82), # Tillamook
    "041059": (45.59, -118.73), # Umatilla
    "041061": (45.31, -118.01), # Union
    "041063": (45.58, -117.18), # Wallowa
    "041065": (45.30, -121.15), # Wasco
    "041067": (45.52, -122.98), # Washington
    "041069": (44.73, -119.98), # Wheeler
    "041071": (45.21, -123.15), # Yamhill

    # Washington FIPS Counties (53xxx / 053xxx)
    "53001": (46.98, -118.42), "053001": (46.98, -118.42), # Adams
    "53003": (46.18, -117.18), "053003": (46.18, -117.18), # Asotin
    "53005": (46.24, -119.51), "053005": (46.24, -119.51), # Benton
    "53007": (47.86, -120.64), "053007": (47.86, -120.64), # Chelan
    "53009": (48.11, -123.43), "053009": (48.11, -123.43), # Clallam
    "53011": (45.78, -122.58), "053011": (45.78, -122.58), # Clark
    "53013": (46.30, -117.91), "053013": (46.30, -117.91), # Columbia
    "53015": (46.18, -122.90), "053015": (46.18, -122.90), # Cowlitz
    "53017": (47.74, -119.69), "053017": (47.74, -119.69), # Douglas
    "53019": (48.47, -118.52), "053019": (48.47, -118.52), # Ferry
    "53021": (46.42, -118.90), "053021": (46.42, -118.90), # Franklin
    "53023": (46.43, -117.53), "053023": (46.43, -117.53), # Garfield
    "53025": (47.21, -119.55), "053025": (47.21, -119.55), # Grant
    "53027": (47.15, -123.83), "053027": (47.15, -123.83), # Grays Harbor
    "53029": (48.16, -122.58), "053029": (48.16, -122.58), # Island
    "53031": (47.78, -123.58), "053031": (47.78, -123.58), # Jefferson
    "53033": (47.49, -121.84), "053033": (47.49, -121.84), # King
    "53035": (47.56, -122.65), "053035": (47.56, -122.65), # Kitsap
    "53037": (47.12, -120.68), "053037": (47.12, -120.68), # Kittitas
    "53039": (45.87, -120.78), "053039": (45.87, -120.78), # Klickitat
    "53041": (46.58, -122.40), "053041": (46.58, -122.40), # Lewis
    "53043": (47.57, -118.42), "053043": (47.57, -118.42), # Lincoln
    "53045": (47.35, -123.18), "053045": (47.35, -123.18), # Mason
    "53047": (48.55, -119.74), "053047": (48.55, -119.74), # Okanogan
    "53049": (46.56, -123.78), "053049": (46.56, -123.78), # Pacific
    "53051": (48.53, -117.27), "053051": (48.53, -117.27), # Pend Oreille
    "53053": (46.90, -122.14), "053053": (46.90, -122.14), # Pierce
    "53055": (48.58, -122.97), "053055": (48.58, -122.97), # San Juan
    "53057": (48.48, -121.68), "053057": (48.48, -121.68), # Skagit
    "53059": (45.90, -121.90), "053059": (45.90, -121.90), # Skamania
    "53061": (48.04, -121.72), "053061": (48.04, -121.72), # Snohomish
    "53063": (47.62, -117.43), "053063": (47.62, -117.43), # Spokane
    "53065": (48.40, -117.85), "053065": (48.40, -117.85), # Stevens
    "53067": (46.93, -122.93), "053067": (46.93, -122.93), # Thurston
    "53069": (46.29, -123.42), "053069": (46.29, -123.42), # Wahkiakum
    "53071": (46.23, -118.39), "053071": (46.23, -118.39), # Walla Walla
    "53073": (48.83, -121.84), "053073": (48.83, -121.84), # Whatcom
    "53075": (46.90, -117.18), "053075": (46.90, -117.18), # Whitman
    "53077": (46.46, -120.74), "053077": (46.46, -120.74), # Yakima

    # Forecast UGC Zones
    "ORZ108": (45.87, -122.85), "ORZ109": (45.52, -122.98), "ORZ110": (45.46, -122.84),
    "ORZ111": (45.52, -122.65), "ORZ112": (45.52, -122.45), "ORZ113": (45.38, -122.52),
    "ORZ114": (45.10, -123.20), "ORZ115": (44.95, -122.95), "ORZ116": (44.56, -123.26),
    "ORZ117": (44.63, -123.10), "ORZ118": (44.05, -123.08), "ORZ119": (45.58, -122.18),
    "ORZ120": (45.60, -122.10), "ORZ123": (45.30, -122.25),
    "ORZ028": (42.40, -121.75), "ORZ622": (42.40, -121.75), "ORZ031": (42.50, -120.30),
    "WAZ204": (46.18, -122.90), "WAZ205": (45.82, -122.58), "WAZ206": (45.65, -122.62),
    "WAZ207": (45.62, -122.40), "WAZ208": (45.90, -122.25), "WAZ209": (45.65, -121.98),
    "WAZ036": (47.62, -117.43),
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
                min_dist = float("inf")

                if alert.geometry and "coordinates" in alert.geometry:
                    geom_type = alert.geometry.get("type")
                    coords = alert.geometry["coordinates"]
                    points: list[tuple[float, float]] = []
                    if geom_type == "Polygon":
                        points = [(pt[1], pt[0]) for ring in coords for pt in ring if len(pt) >= 2]
                    elif geom_type == "MultiPolygon":
                        points = [(pt[1], pt[0]) for poly in coords for ring in poly for pt in ring if len(pt) >= 2]

                    for p_lat, p_lon in points:
                        dist = haversine_miles(self._operator_lat, self._operator_lon, p_lat, p_lon)
                        if dist < min_dist:
                            min_dist = dist

                codes = list(alert.ugc_codes) + list(alert.same_codes)
                for code in codes:
                    if code in KNOWN_CENTROIDS:
                        c_lat, c_lon = KNOWN_CENTROIDS[code]
                        dist = haversine_miles(self._operator_lat, self._operator_lon, c_lat, c_lon)
                        if dist < min_dist:
                            min_dist = dist

                if min_dist <= self._max_radius_miles:
                    filtered.append(alert)

            alerts = tuple(filtered)
        fresh = self._tracker.filter_new_or_updated(alerts)
        for alert in fresh:
            self._sink.record(alert)
        return len(fresh)

