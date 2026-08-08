"""Pure correlation predicate (design doc §5):

    (SAME event code <-> CAP event name)          via the mapping YAML
    AND (SAME FIPS set intersect CAP geocode.SAME) CAP carries geocode.SAME in the same format
    AND (issue times overlap within tolerance)     default +/-5 min

SAME carries no ETN/VTEC, so time-window matching is unavoidable for the
RF leg -- see the design doc §5's own note. `SameEventIn.received_at`
(when `same-decoder` actually decoded the header) stands in for SAME's own
issue time rather than reconstructing a year-less `JJJHHMM` into a real
timestamp: NWR is a live broadcast, so decode time and issue time are
seconds apart in practice, and this sidesteps the year-boundary ambiguity
`JJJHHMM` alone can't resolve.
"""

from __future__ import annotations

from datetime import timedelta

from .mapping import EventMapping
from .models import CapAlertIn, SameEventIn

DEFAULT_TIME_TOLERANCE = timedelta(minutes=5)


def event_names_match(same: SameEventIn, cap: CapAlertIn, mapping: EventMapping) -> bool:
    return mapping.cap_event_for(same.event_code) == cap.event


def fips_overlap(same: SameEventIn, cap: CapAlertIn) -> bool:
    return bool(set(same.fips_codes) & set(cap.same_codes))


def time_overlap(same: SameEventIn, cap: CapAlertIn, tolerance: timedelta = DEFAULT_TIME_TOLERANCE) -> bool:
    return abs((same.received_at - cap.sent).total_seconds()) <= tolerance.total_seconds()


def matches(
    same: SameEventIn,
    cap: CapAlertIn,
    mapping: EventMapping,
    tolerance: timedelta = DEFAULT_TIME_TOLERANCE,
) -> bool:
    return (
        event_names_match(same, cap, mapping)
        and fips_overlap(same, cap)
        and time_overlap(same, cap, tolerance)
    )
