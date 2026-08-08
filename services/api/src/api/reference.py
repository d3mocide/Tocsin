"""Serves the checked-in reference data in `data/` to the browser: SAME
event codes (name + dispatch tier) and the FIPS -> county/state table.

The UI needs both to render an alert the way a person reads one. Without
the tier table a `TOR` looks exactly like an `RWT` on screen, even though
one goes to the mesh immediately and the other is logged and ignored
(design doc §4). Without the FIPS table the affected area reads `041051`
rather than "Multnomah, OR".

Loaded once at startup and served as a static blob rather than joined into
each alert row: it is a few kilobytes that changes only when someone edits
`data/`, so shipping it once and resolving client-side beats denormalizing
it into every alert payload and every SSE frame.

`data/README.md`'s caveat carries through unchanged -- only the Portland
WFO area is seeded, so a code outside that set has no entry and the UI
falls back to showing the raw digits, the same honest degradation
`dispatcher.message` already makes.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReferenceData:
    event_codes: dict[str, dict]
    counties: dict[str, dict]

    def as_dict(self) -> dict:
        return {"event_codes": self.event_codes, "counties": self.counties}


EMPTY = ReferenceData(event_codes={}, counties={})


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


def load(data_dir: Path | None) -> ReferenceData:
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
    return ReferenceData(event_codes=event_codes, counties=counties)
