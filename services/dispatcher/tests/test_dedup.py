from dispatcher.dedup import AlertDeduplicator


def test_first_alert_is_not_a_duplicate():
    dedup = AlertDeduplicator()
    assert dedup.is_duplicate("TOR", ("041051",)) is False


def test_repeated_event_fips_pair_is_a_duplicate_within_ttl():
    dedup = AlertDeduplicator(ttl_seconds=60.0)
    dedup.is_duplicate("TOR", ("041051",), now=0.0)
    assert dedup.is_duplicate("TOR", ("041051",), now=10.0) is True


def test_different_fips_is_not_a_duplicate():
    dedup = AlertDeduplicator(ttl_seconds=60.0)
    dedup.is_duplicate("TOR", ("041051",), now=0.0)
    assert dedup.is_duplicate("TOR", ("041005",), now=0.0) is False


def test_different_event_code_is_not_a_duplicate():
    dedup = AlertDeduplicator(ttl_seconds=60.0)
    dedup.is_duplicate("TOR", ("041051",), now=0.0)
    assert dedup.is_duplicate("SVR", ("041051",), now=0.0) is False


def test_entry_expires_after_ttl():
    dedup = AlertDeduplicator(ttl_seconds=60.0)
    dedup.is_duplicate("TOR", ("041051",), now=0.0)
    assert dedup.is_duplicate("TOR", ("041051",), now=61.0) is False
