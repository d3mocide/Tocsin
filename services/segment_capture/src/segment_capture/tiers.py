"""Event-code -> (name, tier) lookup, loaded from the checked-in
`data/same_event_codes.yaml` (design doc §4, §9: shared reference data
lives under `data/`, not duplicated per service).

Deliberately duplicated from `same_decoder.tiers` rather than imported --
service boundary (CLAUDE.md). `segment_capture` already runs its own
independent ZCZC detection (`boundary.py`'s own docstring); this completes
that independence for tier as well, so stage 2 (Phase 7's `dispatcher`)
can gate on Tier A using a tier value computed from *this* pipeline's own
event-code parse, not one borrowed from `same_decoder`'s structurally
separate multimon-ng instance.
"""

from __future__ import annotations

from pathlib import Path

import yaml

UNKNOWN_CODE_TIER = "B"


def _default_data_dir(module_file: str = __file__) -> Path:
    here = Path(module_file).resolve()
    parents = here.parents
    if len(parents) <= 4:
        raise RuntimeError(
            f"can't infer a default data/ directory from {here} (not a full source "
            "checkout) -- pass data_dir explicitly, or set TOCSIN_DATA_DIR"
        )
    return parents[4] / "data"


class TierTable:
    def __init__(self, codes: dict[str, dict[str, str]]):
        self._codes = codes

    @classmethod
    def load(cls, data_dir: Path | None = None) -> "TierTable":
        path = (data_dir or _default_data_dir()) / "same_event_codes.yaml"
        with path.open() as f:
            codes = yaml.safe_load(f) or {}
        return cls(codes)

    def lookup(self, event_code: str) -> tuple[str, str]:
        entry = self._codes.get(event_code)
        if entry is None:
            return (f"Unknown event code {event_code}", UNKNOWN_CODE_TIER)
        return (entry["name"], entry["tier"])
