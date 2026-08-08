from datetime import timedelta

from fusion.correlator import matches

from fixtures import CLACKAMAS, MULTNOMAH, TOR_MAPPING, BASE_TIME, cap_alert, same_event


def test_true_match():
    same = same_event(event_code="TOR", fips_codes=(MULTNOMAH,))
    cap = cap_alert(event="Tornado Warning", same_codes=(MULTNOMAH,))
    assert matches(same, cap, TOR_MAPPING) is True


def test_true_match_with_partial_fips_overlap():
    # SAME and CAP don't have to name the exact same set of counties, just
    # share at least one -- design doc §5's "intersection", not "subset".
    same = same_event(fips_codes=(MULTNOMAH, CLACKAMAS))
    cap = cap_alert(same_codes=(CLACKAMAS, "041999"))
    assert matches(same, cap, TOR_MAPPING) is True


def test_near_miss_right_event_wrong_county():
    same = same_event(event_code="TOR", fips_codes=(MULTNOMAH,))
    cap = cap_alert(event="Tornado Warning", same_codes=(CLACKAMAS,))
    assert matches(same, cap, TOR_MAPPING) is False


def test_near_miss_wrong_event_right_county():
    same = same_event(event_code="TOR", fips_codes=(MULTNOMAH,))
    cap = cap_alert(event="Severe Thunderstorm Warning", same_codes=(MULTNOMAH,))
    assert matches(same, cap, TOR_MAPPING) is False


def test_near_miss_event_code_with_no_cap_equivalent_never_matches():
    same = same_event(event_code="RWT", fips_codes=(MULTNOMAH,))
    cap = cap_alert(event="Required Weekly Test", same_codes=(MULTNOMAH,))
    assert matches(same, cap, TOR_MAPPING) is False


def test_within_time_tolerance_matches():
    same = same_event(received_at=BASE_TIME)
    cap = cap_alert(sent=BASE_TIME + timedelta(minutes=4, seconds=59))
    assert matches(same, cap, TOR_MAPPING) is True


def test_outside_time_tolerance_does_not_match():
    same = same_event(received_at=BASE_TIME)
    cap = cap_alert(sent=BASE_TIME + timedelta(minutes=5, seconds=1))
    assert matches(same, cap, TOR_MAPPING) is False


def test_cap_leading_same_within_tolerance_also_matches():
    # Symmetric: the API can lead the RF header too, not just lag it.
    same = same_event(received_at=BASE_TIME)
    cap = cap_alert(sent=BASE_TIME - timedelta(minutes=3))
    assert matches(same, cap, TOR_MAPPING) is True


def test_custom_tolerance_is_respected():
    same = same_event(received_at=BASE_TIME)
    cap = cap_alert(sent=BASE_TIME + timedelta(minutes=1))
    assert matches(same, cap, TOR_MAPPING, tolerance=timedelta(seconds=30)) is False
