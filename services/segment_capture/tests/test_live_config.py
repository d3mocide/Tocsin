"""`LIVE_TRANSCRIPTION_*` env parsing (`segment_capture._live_channel`).

The site-name cases below are regressions from a real deployment, not
hypotheticals: `LIVE_TRANSCRIPTION_SITE` was set to a whole
`SDR_RX_DEVICES` entry, which named a ring buffer directory that never
existed (see docs/design/tracking.md, 2026-08-14).
"""

import segment_capture
from segment_capture import normalize_site


def _enable(monkeypatch, site: str, channel: str = "WX7") -> None:
    monkeypatch.setenv("LIVE_TRANSCRIPTION_ENABLED", "true")
    monkeypatch.setenv("LIVE_TRANSCRIPTION_SITE", site)
    monkeypatch.setenv("LIVE_TRANSCRIPTION_CHANNEL", channel)


def test_plain_site_name_passes_through():
    assert normalize_site("PDX") == "PDX"


def test_whole_sdr_rx_devices_entry_yields_the_site_half():
    assert normalize_site("PDX:49435794") == "PDX"


def test_surrounding_whitespace_is_stripped():
    assert normalize_site("  PDX : 49435794  ") == "PDX"


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("LIVE_TRANSCRIPTION_ENABLED", raising=False)
    assert segment_capture._live_channel() is None


def test_enabled_with_a_plain_site(monkeypatch):
    _enable(monkeypatch, "PDX")
    assert segment_capture._live_channel() == ("PDX", "WX7")


def test_enabled_with_a_pasted_device_entry_is_accepted_and_reported(monkeypatch, capsys):
    _enable(monkeypatch, "PDX:49435794")
    assert segment_capture._live_channel() == ("PDX", "WX7")
    err = capsys.readouterr().err
    assert "looks like a whole SDR_RX_DEVICES entry" in err
    assert "'PDX'" in err


def test_a_plain_site_reports_nothing(monkeypatch, capsys):
    _enable(monkeypatch, "PDX")
    segment_capture._live_channel()
    assert capsys.readouterr().err == ""


def test_channel_is_upper_cased(monkeypatch):
    _enable(monkeypatch, "PDX", channel="wx7")
    assert segment_capture._live_channel() == ("PDX", "WX7")


def test_missing_site_disables_with_a_warning(monkeypatch, capsys):
    _enable(monkeypatch, "", channel="WX7")
    assert segment_capture._live_channel() is None
    assert "requires both" in capsys.readouterr().err


def test_missing_channel_disables_with_a_warning(monkeypatch, capsys):
    _enable(monkeypatch, "PDX", channel="")
    assert segment_capture._live_channel() is None
    assert "requires both" in capsys.readouterr().err
