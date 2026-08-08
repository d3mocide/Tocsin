from segment_capture.boundary import is_eom, parse_message_start


def test_parses_event_code_and_fips():
    start = parse_message_start("EAS: ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-")
    assert start is not None
    assert start.event_code == "TOR"
    assert start.fips_codes == ("017021",)


def test_parses_multiple_fips_codes():
    start = parse_message_start("ZCZC-WXR-SVR-017021-017023+0045-1000042-KILX/NWS-")
    assert start is not None
    assert start.fips_codes == ("017021", "017023")


def test_non_header_line_returns_none():
    assert parse_message_start("EAS: NNNN") is None
    assert parse_message_start("garbled nonsense") is None


def test_is_eom_detects_nnnn():
    assert is_eom("EAS: NNNN") is True
    assert is_eom("NNNN") is True


def test_is_eom_false_for_header_or_garbage():
    assert is_eom("ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-") is False
    assert is_eom("garbled nonsense") is False
