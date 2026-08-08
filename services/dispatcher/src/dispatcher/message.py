"""Stage-1 message template (design doc §7): deterministic, <=140 bytes,
built entirely from the SAME header's own fields -- no STT, no LLM, no API
lookup. Every value here traces back to one decoded `ZCZC` line:

    TOR WARN | Multnomah,Clackamas OR | exp 2145Z | RF

`WARN` is a fixed literal, not derived per event -- every Tier A code is
some flavor of immediate-threat warning (`data/same_event_codes.yaml`'s
own Tier A comment), and the design doc's own example composes it as a
plain suffix rather than deriving it from the event name.

`purge_minutes` is an *offset* from issue time, not an absolute time
(design doc §4) -- `received_at` (see `fusion.correlator`'s identical
reasoning: same_decoder's decode-time timestamp stands in for SAME's own
year-less `JJJHHMM` issue time) plus that offset gives the absolute
expiry this template shows.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .fips import FipsTable

MAX_BYTES = 140
TRUNCATION_MARKER = "..."


def build_stage1_message(
    event_code: str,
    fips_codes: tuple[str, ...],
    purge_minutes: int,
    received_at: datetime,
    fips_table: FipsTable,
) -> str:
    expiry = received_at + timedelta(minutes=purge_minutes)
    counties, state = _describe_area(fips_codes, fips_table)
    area = f"{counties} {state}".strip()
    message = f"{event_code} WARN | {area} | exp {expiry:%H%M}Z | RF"
    return _truncate_to_bytes(message, MAX_BYTES)


def _describe_area(fips_codes: tuple[str, ...], fips_table: FipsTable) -> tuple[str, str]:
    names = []
    state = ""
    for code in fips_codes:
        entry = fips_table.lookup(code)
        if entry is None:
            # Outside the seeded WFO area (data/README.md) -- show the raw
            # code rather than silently dropping the county from the
            # message.
            names.append(code)
            continue
        names.append(entry.county)
        # First state seen wins; a SAME header spanning two states (e.g.
        # Portland WFO's OR+WA coverage) only gets one state shown here --
        # a known simplification, not a rounding error to chase.
        state = state or entry.state
    return ",".join(names), state


def _truncate_to_bytes(message: str, max_bytes: int) -> str:
    encoded = message.encode("ascii", errors="replace")
    if len(encoded) <= max_bytes:
        return message
    keep = max_bytes - len(TRUNCATION_MARKER)
    return encoded[:keep].decode("ascii", errors="ignore") + TRUNCATION_MARKER
