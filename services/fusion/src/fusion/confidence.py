"""Mode-relative confidence for an `Alert`'s state (design doc §5):
"Confidence must be mode-relative... deployment mode is an input to the
confidence calculation." In `hybrid`, `RF_ONLY` means the API lagged or
disagreed -- mildly interesting. In `offgrid`, `RF_ONLY` is the *only*
possible state, so scoring it low would show a permanent warning light on
a perfectly healthy off-grid system. `API_ONLY` can't occur in `offgrid`
at all (`nws-poller` isn't running there -- design doc §8), so its offgrid
score below is a defensive placeholder, never expected to be read for
real.
"""

from __future__ import annotations

from .models import AlertState

OFFGRID = "offgrid"
HYBRID = "hybrid"

_CONFIRMED_CONFIDENCE = 1.0

_RF_ONLY_CONFIDENCE = {
    OFFGRID: 0.95,  # the only possible state off-grid; not a warning sign
    HYBRID: 0.6,  # the API lagged or disagreed -- mildly interesting
}

_API_ONLY_CONFIDENCE = {
    HYBRID: 0.7,  # transmitter down, out of footprint, or a non-broadcast product
    OFFGRID: 0.0,  # can't happen: nws-poller doesn't run off-grid (design doc §8)
}


def compute_confidence(state: AlertState, mode: str) -> float:
    if state == AlertState.CONFIRMED:
        return _CONFIRMED_CONFIDENCE
    if state == AlertState.RF_ONLY:
        return _RF_ONLY_CONFIDENCE[mode]
    if state == AlertState.API_ONLY:
        return _API_ONLY_CONFIDENCE[mode]
    raise ValueError(f"unknown alert state: {state}")
