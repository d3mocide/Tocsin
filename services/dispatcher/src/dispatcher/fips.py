"""FIPS -> county/state lookup, loaded from the checked-in `data/fips.csv`
(design doc §9: "fips.csv -- FIPS -> county name, for templating").

`data/README.md`'s own caveat applies here: only the Portland, OR WFO area
is seeded, so a FIPS code outside that set has no entry -- `message.py`
falls back to showing the raw code in that case rather than dropping the
county from the message, which is the honest behavior to route around
here, not a bug to fix in this module.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


def _default_data_dir(module_file: str = __file__) -> Path:
    here = Path(module_file).resolve()
    parents = here.parents
    if len(parents) <= 4:
        raise RuntimeError(
            f"can't infer a default data/ directory from {here} (not a full source "
            "checkout) -- pass data_dir explicitly, or set TOCSIN_DATA_DIR"
        )
    return parents[4] / "data"


@dataclass(frozen=True)
class FipsEntry:
    county: str
    state: str


class FipsTable:
    def __init__(self, entries: dict[str, FipsEntry]):
        self._entries = entries

    @classmethod
    def load(cls, data_dir: Path | None = None) -> "FipsTable":
        path = (data_dir or _default_data_dir()) / "fips.csv"
        entries = {}
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                entries[row["fips"]] = FipsEntry(county=row["county"], state=row["state"])
        return cls(entries)

    def lookup(self, same_fips_code: str) -> FipsEntry | None:
        """`same_fips_code` is SAME's 6-digit `PSSCCC` (design doc §4): `P`
        is the county-subdivision digit, `SSCCC` is the plain 5-digit FIPS
        `fips.csv` keys on. This table doesn't distinguish subdivisions --
        that matches `fips.csv`'s own granularity, there's nothing finer to
        look up."""
        plain_fips = same_fips_code[-5:]
        return self._entries.get(plain_fips)
