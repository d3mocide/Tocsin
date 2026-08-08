"""Shared fixture builders for correlation tests -- realistic SAME events
and CAP alerts, close enough to real payloads (design doc §4, §5 field
shapes) to exercise the actual correlation predicate rather than
hand-wavy stand-ins."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fusion.mapping import EventMapping
from fusion.models import CapAlertIn, SameEventIn

MULTNOMAH = "041051"
CLACKAMAS = "041005"
WASHINGTON = "041067"

TOR_MAPPING = EventMapping({"TOR": "Tornado Warning", "SVR": "Severe Thunderstorm Warning"})

BASE_TIME = datetime(2026, 8, 8, 21, 32, tzinfo=timezone.utc)


def same_event(
    event_code: str = "TOR",
    event_name: str = "Tornado Warning",
    fips_codes: tuple[str, ...] = (MULTNOMAH,),
    received_at: datetime = BASE_TIME,
    tier: str = "A",
) -> SameEventIn:
    return SameEventIn(
        site="home",
        channel="WX5",
        received_at=received_at,
        event_code=event_code,
        event_name=event_name,
        tier=tier,
        fips_codes=fips_codes,
        originator="WXR",
        callsign="KPQR/NWS",
        purge_minutes=45,
        raw_header=f"ZCZC-WXR-{event_code}-{'-'.join(fips_codes)}+0045-2202132-KPQR/NWS-",
    )


def cap_alert(
    event: str = "Tornado Warning",
    same_codes: tuple[str, ...] = (MULTNOMAH,),
    sent: datetime = BASE_TIME,
    id: str = "urn:oid:2.49.0.1.840.0.example",
    status: str = "Actual",
) -> CapAlertIn:
    return CapAlertIn(
        id=id,
        event=event,
        headline=f"{event} issued",
        status=status,
        message_type="Alert",
        category="Met",
        severity="Extreme",
        certainty="Observed",
        urgency="Immediate",
        area_desc="Multnomah, OR",
        sent=sent,
        effective=sent,
        onset=sent,
        expires=sent + timedelta(hours=1),
        ends=sent + timedelta(hours=1),
        same_codes=same_codes,
        ugc_codes=("ORZ006",),
        vtec="/O.NEW.KPQR.TO.W.0012.260808T2132Z-260808T2215Z/",
    )
