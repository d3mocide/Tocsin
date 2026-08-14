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


def test_transcript_only_is_below_rf_only_in_both_modes():
    for mode in ("offgrid", "hybrid"):
        assert compute_confidence(AlertState.TRANSCRIPT_ONLY, mode) < compute_confidence(AlertState.RF_ONLY, mode)


def test_transcript_only_is_not_the_offgrid_free_pass_rf_only_gets():
    """Unlike RF_ONLY, being the only signal available off-grid does not
    push TRANSCRIPT_ONLY's confidence up near 1.0 -- it's still a fuzzy
    keyword match, not a decoded SAME header."""
    assert compute_confidence(AlertState.TRANSCRIPT_ONLY, "offgrid") < 0.7


def test_transcript_only_is_lower_in_hybrid_than_offgrid():
    offgrid = compute_confidence(AlertState.TRANSCRIPT_ONLY, "offgrid")
    hybrid = compute_confidence(AlertState.TRANSCRIPT_ONLY, "hybrid")
    assert offgrid > hybrid > 0.0
