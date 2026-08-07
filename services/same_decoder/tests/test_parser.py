from same_decoder.parser import parse_same_header


def test_parses_multi_fips_tornado_warning():
    header = parse_same_header("ZCZC-WXR-TOR-017021-017115+0045-1000042-KILX/NWS-")
    assert header is not None
    assert header.originator == "WXR"
    assert header.event_code == "TOR"
    assert header.fips_codes == ("017021", "017115")
    assert header.purge_code == "0045"
    assert header.purge_minutes == 45
    assert header.issue_day_of_year == 100
    assert header.issue_hour == 0
    assert header.issue_minute == 42
    assert header.callsign == "KILX/NWS"


def test_parses_required_weekly_test_with_many_fips():
    line = (
        "ZCZC-WXR-RWT-018139-018109-018059-018159-018065-018011-018057-018035-"
        "018145-018095-018063-018097-018031-018081+0600-0441610-KIND/NWS-"
    )
    header = parse_same_header(line)
    assert header is not None
    assert header.event_code == "RWT"
    assert len(header.fips_codes) == 14
    assert header.fips_codes[0] == "018139"
    assert header.fips_codes[-1] == "018081"
    assert header.purge_minutes == 360
    assert header.issue_day_of_year == 44
    assert header.issue_hour == 16
    assert header.issue_minute == 10


def test_tolerates_a_decoder_prefix_before_the_header():
    header = parse_same_header("EAS: ZCZC-WXR-RWT-018139+0030-2761515-KLWX/NWS-")
    assert header is not None
    assert header.event_code == "RWT"
    assert header.raw == "ZCZC-WXR-RWT-018139+0030-2761515-KLWX/NWS-"


def test_tolerates_trailing_noise_after_the_header():
    header = parse_same_header("ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-\x00\x00garbage")
    assert header is not None
    assert header.event_code == "TOR"


def test_returns_none_for_a_non_zczc_line():
    assert parse_same_header("EAS: NNNN") is None
    assert parse_same_header("") is None
    assert parse_same_header("some unrelated multimon-ng output") is None


def test_returns_none_for_a_header_too_garbled_to_match():
    # missing the purge/issue separator entirely -- not just noisy digits
    assert parse_same_header("ZCZC-WXR-TOR-01702informationlost") is None


def test_single_digit_subdivision_fips_still_six_digits():
    header = parse_same_header("ZCZC-CIV-CEM-541011+0015-2000000-WXYZ/EM-")
    assert header is not None
    assert header.fips_codes == ("541011",)
    assert header.originator == "CIV"
