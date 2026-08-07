from same_decoder.dedup import HeaderDeduplicator
from same_decoder.parser import parse_same_header

HEADER_A = parse_same_header("ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-")
HEADER_B = parse_same_header("ZCZC-WXR-SVR-017021+0030-1000042-KILX/NWS-")


def test_first_sighting_is_not_a_duplicate():
    dedup = HeaderDeduplicator()
    assert dedup.is_duplicate(HEADER_A, now=0.0) is False


def test_repeat_within_ttl_is_a_duplicate():
    dedup = HeaderDeduplicator(ttl_seconds=60.0)
    dedup.is_duplicate(HEADER_A, now=0.0)
    assert dedup.is_duplicate(HEADER_A, now=5.0) is True


def test_repeat_after_ttl_expires_is_not_a_duplicate():
    dedup = HeaderDeduplicator(ttl_seconds=60.0)
    dedup.is_duplicate(HEADER_A, now=0.0)
    assert dedup.is_duplicate(HEADER_A, now=61.0) is False


def test_different_headers_are_independent():
    dedup = HeaderDeduplicator()
    assert dedup.is_duplicate(HEADER_A, now=0.0) is False
    assert dedup.is_duplicate(HEADER_B, now=0.0) is False
