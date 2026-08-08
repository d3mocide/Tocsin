from fusion.mapping import EventMapping


def test_known_code_maps_to_cap_event_text():
    mapping = EventMapping({"TOR": "Tornado Warning"})
    assert mapping.cap_event_for("TOR") == "Tornado Warning"
    assert mapping.has_cap_equivalent("TOR") is True


def test_unmapped_code_returns_none():
    mapping = EventMapping({"TOR": "Tornado Warning"})
    assert mapping.cap_event_for("RWT") is None
    assert mapping.has_cap_equivalent("RWT") is False


def test_load_reads_the_checked_in_data_file():
    mapping = EventMapping.load()
    assert mapping.cap_event_for("TOR") == "Tornado Warning"
    assert mapping.cap_event_for("SVR") == "Severe Thunderstorm Warning"
