"""GeoJSON feature (one CAP alert) -> structured `CapAlert` (design doc §5).

NWS CAP payloads carry `geocode.SAME` in the same 6-digit `PSSCCC` format
as SAME/EAS FIPS codes (design doc §5: "CAP payloads from NWS carry
geocode.SAME") -- that's what lets `fusion` correlate by direct set
intersection instead of a county-name lookup in between.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CapAlert:
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


def _parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def parse_feature(feature: dict) -> CapAlert:
    props = feature["properties"]
    geocode = props.get("geocode") or {}
    vtec_values = (props.get("parameters") or {}).get("VTEC") or []
    return CapAlert(
        id=props["id"],
        event=props["event"],
        headline=props.get("headline"),
        status=props["status"],
        message_type=props["messageType"],
        category=props["category"],
        severity=props["severity"],
        certainty=props["certainty"],
        urgency=props["urgency"],
        area_desc=props.get("areaDesc", ""),
        sent=_parse_time(props["sent"]),
        effective=_parse_time(props.get("effective")),
        onset=_parse_time(props.get("onset")),
        expires=_parse_time(props.get("expires")),
        ends=_parse_time(props.get("ends")),
        same_codes=tuple(geocode.get("SAME") or ()),
        ugc_codes=tuple(geocode.get("UGC") or ()),
        vtec=vtec_values[0] if vtec_values else None,
    )
