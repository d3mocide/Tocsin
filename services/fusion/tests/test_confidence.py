import pytest

from fusion.confidence import compute_confidence
from fusion.models import AlertState


def test_confirmed_is_always_high_confidence_regardless_of_mode():
    assert compute_confidence(AlertState.CONFIRMED, "offgrid") == 1.0
    assert compute_confidence(AlertState.CONFIRMED, "hybrid") == 1.0


def test_rf_only_is_high_confidence_offgrid_where_it_is_the_only_possible_state():
    offgrid = compute_confidence(AlertState.RF_ONLY, "offgrid")
    hybrid = compute_confidence(AlertState.RF_ONLY, "hybrid")
    assert offgrid > hybrid
    assert offgrid >= 0.9


def test_rf_only_is_mildly_interesting_in_hybrid():
    hybrid = compute_confidence(AlertState.RF_ONLY, "hybrid")
    assert 0.0 < hybrid < 0.9


def test_api_only_only_meaningful_in_hybrid():
    assert compute_confidence(AlertState.API_ONLY, "hybrid") > 0.0
    assert compute_confidence(AlertState.API_ONLY, "offgrid") == 0.0


def test_unknown_state_raises():
    with pytest.raises(ValueError):
        compute_confidence("bogus", "offgrid")
