"""Event-code -> (name, tier) lookup, loaded from the checked-in
`data/same_event_codes.yaml` (design doc §4, §9: shared reference data
lives under `data/`, not duplicated per service).
"""

from __future__ import annotations

from pathlib import Path

import yaml

UNKNOWN_CODE_TIER = "B"

# services/same_decoder/src/same_decoder/tiers.py -> repo root is 4 parents
# up, but ONLY in a full source checkout. Inside the Docker image, the
# copied tree is flattened to /app/src/same_decoder/tiers.py with nothing 4
# parents up -- .parents[4] raises IndexError there. Deployed contexts are
# expected to always pass an explicit data_dir (compose.yaml sets
# TOCSIN_DATA_DIR), so this is computed lazily, only when load() is called
# with no override, instead of as an eagerly-evaluated module constant that
# would crash on import regardless of whether it's ever used.
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
    """`event_code` -> (name, tier). Unknown codes fall back to Tier B
    (MQTT-only, not silently dropped, not auto-escalated to mesh) rather
    than raising -- NWS revises the code list periodically (data/README.md),
    and an unrecognized code is far more likely to mean the list needs
    updating than that the message should be ignored."""

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
