"""Event-code -> (name, tier) lookup, loaded from the checked-in
`data/same_event_codes.yaml` (design doc §4, §9: shared reference data
lives under `data/`, not duplicated per service).
"""

from __future__ import annotations

from pathlib import Path

import yaml

# services/same_decoder/src/same_decoder/tiers.py -> repo root is 4 parents up.
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[4] / "data"

UNKNOWN_CODE_TIER = "B"


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
        path = (data_dir or DEFAULT_DATA_DIR) / "same_event_codes.yaml"
        with path.open() as f:
            codes = yaml.safe_load(f) or {}
        return cls(codes)

    def lookup(self, event_code: str) -> tuple[str, str]:
        entry = self._codes.get(event_code)
        if entry is None:
            return (f"Unknown event code {event_code}", UNKNOWN_CODE_TIER)
        return (entry["name"], entry["tier"])
