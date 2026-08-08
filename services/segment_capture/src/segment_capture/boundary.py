"""ZCZC (message start) / NNNN (end-of-message) line detection from
multimon-ng's `-a EAS` output (design doc §4).

Deliberately not a shared import from `same_decoder` -- services
communicate over ZMQ, not Python imports, across the service boundary (see
CLAUDE.md). `same_decoder` already parses the full ZCZC header for tiering
and dedup; this duplicates only the small amount of that knowledge
`segment_capture` actually needs (that a message started, and which event/
FIPS it's for, to name the capture) to decide when to start/stop recording
-- it does not need tiers, dedup, or originator/callsign.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ZCZC_PATTERN = re.compile(
    r"ZCZC-(?P<org>[A-Z]{3})-(?P<event>[A-Z]{3})-"
    r"(?P<fips>\d{6}(?:-\d{6}){0,30})"
    r"\+(?P<purge>\d{4})-(?P<issue>\d{7})-(?P<callsign>[^-\s]{1,8})-"
)
_EOM_PATTERN = re.compile(r"NNNN")


@dataclass(frozen=True)
class MessageStart:
    raw: str
    event_code: str
    fips_codes: tuple[str, ...]


def parse_message_start(line: str) -> MessageStart | None:
    match = _ZCZC_PATTERN.search(line)
    if match is None:
        return None
    return MessageStart(
        raw=match.group(0),
        event_code=match.group("event"),
        fips_codes=tuple(match.group("fips").split("-")),
    )


def is_eom(line: str) -> bool:
    return _EOM_PATTERN.search(line) is not None
