"""Serves the checked-in reference data in `data/` to the browser: SAME
event codes (name + dispatch tier), the FIPS -> county/state table, and the
NWR transmitter station list.

The UI needs the first two to render an alert the way a person reads one.
Without the tier table a `TOR` looks exactly like an `RWT` on screen, even
though one goes to the mesh immediately and the other is logged and ignored
(design doc §4). Without the FIPS table the affected area reads `041051`
rather than "Multnomah, OR". The station list (`data/nwr_stations_or.yaml`)
lets the UI show which NWR transmitters an operator is likely receiving --
each entry gets a `distance_km` from the operator's location when
`TOCSIN_LATITUDE`/`TOCSIN_LONGITUDE` are configured (see `ApiConfig`), and
`null` when they aren't or when the station's own coordinates are unknown
(that file's header comment covers which two).

Loaded once at startup and served as a static blob rather than joined into
each alert row: it is a few kilobytes that changes only when someone edits
`data/` or the operator's configured location, so shipping it once and
resolving client-side beats denormalizing it into every alert payload and
every SSE frame.

`data/README.md`'s caveat carries through unchanged -- only the Portland
WFO area is seeded for FIPS, so a code outside that set has no entry and
the UI falls back to showing the raw digits, the same honest degradation
`dispatcher.message` already makes.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReferenceData:
    event_codes: dict[str, dict]
    counties: dict[str, dict]
    stations: dict[str, dict]

    def as_dict(self) -> dict:
        return {"event_codes": self.event_codes, "counties": self.counties, "stations": self.stations}


EMPTY = ReferenceData(event_codes={}, counties={}, stations={})

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points. Good to well under
    a percent at NWR transmitter ranges (tens to low hundreds of km) --
    Earth's ellipsoidal flattening isn't worth the complexity here, this is
    a "how far is that transmitter" UI hint, not a navigation input."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def load_event_codes(path: Path) -> dict[str, dict]:
    import yaml

    with path.open() as f:
        raw = yaml.safe_load(f) or {}
    return {
        code: {"name": entry.get("name", code), "tier": entry.get("tier")}
        for code, entry in raw.items()
        if isinstance(entry, dict)
    }


def load_counties(path: Path) -> dict[str, dict]:
    counties = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            counties[row["fips"]] = {"county": row["county"], "state": row["state"]}
    return counties


def load_stations(path: Path, operator_lat: float | None, operator_lon: float | None) -> dict[str, dict]:
    """`operator_lat`/`operator_lon` unset means every entry's `distance_km`
    is `null` -- there's no location to measure from. A station missing its
    own `lat`/`lon` (see `data/nwr_stations_or.yaml`'s header) gets `null`
    too rather than a fabricated distance."""
    import yaml

    with path.open() as f:
        raw = yaml.safe_load(f) or {}
    have_operator_location = operator_lat is not None and operator_lon is not None
    stations = {}
    for callsign, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        lat, lon = entry.get("lat"), entry.get("lon")
        distance_km = (
            round(haversine_km(operator_lat, operator_lon, lat, lon), 1)
            if have_operator_location and lat is not None and lon is not None
            else None
        )
        distance_miles = round(distance_km * 0.621371, 1) if distance_km is not None else None
        stations[callsign] = {
            "name": entry.get("name"),
            "frequency_mhz": entry.get("frequency_mhz"),
            "status": entry.get("status"),
            "wfo": entry.get("wfo"),
            "power_watts": entry.get("power_watts"),
            "lat": lat,
            "lon": lon,
            "distance_km": distance_km,
            "distance_miles": distance_miles,
        }
    return stations


def load(
    data_dir: Path | None,
    operator_lat: float | None = None,
    operator_lon: float | None = None,
) -> ReferenceData:
    """Returns `EMPTY` rather than raising when `data_dir` is unset or a
    file is missing. Every other service that reads `data/` exits 1
    instead -- correctly, since a decoder with no tier table would
    silently mis-tier a tornado warning. Here the stake is only that the
    UI shows raw codes instead of county names, and refusing to serve the
    alert feed at all over a cosmetic lookup table would be the worse
    failure."""
    if data_dir is None:
        return EMPTY
    event_codes_path = data_dir / "same_event_codes.yaml"
    fips_path = data_dir / "fips.csv"
    event_codes = load_event_codes(event_codes_path) if event_codes_path.is_file() else {}
    counties = load_counties(fips_path) if fips_path.is_file() else {}

    stations = {}
    stations_dir = data_dir / "nwr_stations"
    if stations_dir.is_dir():
        for yaml_file in sorted(stations_dir.glob("*.yaml")):
            stations.update(load_stations(yaml_file, operator_lat, operator_lon))

    if not stations:
        stations_path = data_dir / "nwr_stations.yaml"
        if not stations_path.is_file():
            stations_path = data_dir / "nwr_stations_or.yaml"
        if stations_path.is_file():
            stations = load_stations(stations_path, operator_lat, operator_lon)

    return ReferenceData(event_codes=event_codes, counties=counties, stations=stations)
