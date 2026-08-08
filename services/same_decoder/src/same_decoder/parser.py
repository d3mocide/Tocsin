"""ZCZC SAME header parsing (design doc §4).

Format: `ZCZC-ORG-EEE-PSSCCC-PSSCCC+TTTT-JJJHHMM-LLLLLLLL-`

- `ORG` -- 3-char originator (WXR, CIV, EAS, PEP, EAN)
- `EEE` -- 3-char event code
- `PSSCCC` -- 6-digit FIPS, repeatable up to 31 times; `P` is the county
  subdivision digit
- `+TTTT` -- purge time, HHMM *offset* from issue time (not absolute)
- `JJJHHMM` -- issue time: day-of-year, hour, minute (UTC)
- `LLLLLLLL` -- originating station callsign, up to 8 chars (commonly
  `CALL/ORG`, e.g. `KLWX/NWS` -- note the `/` is part of the field)

The header is transmitted three times; per the design doc, multimon-ng
itself only emits a decoded line once two of the three copies agree, so by
the time a line reaches this parser it's already been through that
majority-vote filter. This parser's job is narrower: don't crash or
misparse on whatever multimon-ng hands it. `.search()` (not `.match()`)
so a decoder-added prefix like `EAS: ` doesn't need special-casing, and a
line that doesn't contain a well-formed header simply parses to `None`
rather than raising.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ZCZC_PATTERN = re.compile(
    r"ZCZC-(?P<org>[A-Z]{3})-(?P<event>[A-Z]{3})-"
    r"(?P<fips>\d{6}(?:-\d{6}){0,30})"
    r"\+(?P<purge>\d{4})-(?P<issue>\d{7})-(?P<callsign>[^-\s]{1,8})-"
)


@dataclass(frozen=True)
class SameHeader:
    raw: str
    originator: str
    event_code: str
    fips_codes: tuple[str, ...]
    purge_code: str
    purge_minutes: int
    issue_day_of_year: int
    issue_hour: int
    issue_minute: int
    callsign: str


def parse_same_header(line: str) -> SameHeader | None:
    match = _ZCZC_PATTERN.search(line)
    if match is None:
        return None
    purge = match.group("purge")
    issue = match.group("issue")
    return SameHeader(
        raw=match.group(0),
        originator=match.group("org"),
        event_code=match.group("event"),
        fips_codes=tuple(match.group("fips").split("-")),
        purge_code=purge,
        purge_minutes=int(purge[:2]) * 60 + int(purge[2:]),
        issue_day_of_year=int(issue[:3]),
        issue_hour=int(issue[3:5]),
        issue_minute=int(issue[5:7]),
        callsign=match.group("callsign"),
    )
