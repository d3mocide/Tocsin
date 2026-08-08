"""SAME event code -> CAP `event` text, loaded from the checked-in
`data/same_to_cap.yaml` (design doc §5, §9: shared reference data lives
under `data/`, not duplicated per service).

Mirrors `same_decoder.tiers`'s loader shape, including its lazy
default-data-dir fix: `.parents[N]` only resolves to the repo root in a
full source checkout, not inside a flattened Docker image tree, so it must
never be a module-level constant evaluated at import time (that exact bug
crash-looped `same-decoder`'s container -- see `docs/design/tracking.md`,
2026-08-08).
"""

from __future__ import annotations

from pathlib import Path

import yaml


def _default_data_dir(module_file: str = __file__) -> Path:
    here = Path(module_file).resolve()
    parents = here.parents
    if len(parents) <= 4:
        raise RuntimeError(
            f"can't infer a default data/ directory from {here} (not a full source "
            "checkout) -- pass data_dir explicitly, or set TOCSIN_DATA_DIR"
        )
    return parents[4] / "data"


class EventMapping:
    """`same_event_code` -> CAP `event` text, or `None` for SAME codes with
    no CAP equivalent (administrative/test codes -- see the comment at the
    bottom of `data/same_to_cap.yaml`). A code absent from the mapping
    entirely is treated the same as an explicit `None`: it can never
    correlate, so the correlator should stop waiting for a CAP match and
    resolve straight to `RF_ONLY` rather than sitting open until a
    time-window timeout."""

    def __init__(self, codes: dict[str, str]):
        self._codes = codes

    @classmethod
    def load(cls, data_dir: Path | None = None) -> "EventMapping":
        path = (data_dir or _default_data_dir()) / "same_to_cap.yaml"
        with path.open() as f:
            codes = yaml.safe_load(f) or {}
        return cls(codes)

    def cap_event_for(self, same_event_code: str) -> str | None:
        return self._codes.get(same_event_code)

    def has_cap_equivalent(self, same_event_code: str) -> bool:
        return self.cap_event_for(same_event_code) is not None
