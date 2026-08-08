import pytest

import sdr_rx
from sdr_rx import main


def test_main_reports_bad_device_spec_cleanly(monkeypatch, capsys):
    """A bare serial (no 'site:' prefix) -- the mistake in the field -- must
    print one clear message and exit, not an uncaught traceback."""
    monkeypatch.setenv("SDR_RX_DEVICES", "49435794")

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "SDR_RX_DEVICES" in err
    assert "site:serial" in err


def test_main_passes_sdr_rx_gain_db_through_to_the_device(monkeypatch):
    """SDR_RX_GAIN_DB must actually reach SoapySDRDevice, not just parse --
    real device construction needs target hardware, so this stands in with
    a fake that records its gain_db and fails fast (same shape as the real
    "bindings not installed" RuntimeError path main() already handles),
    rather than spinning up a real capture thread `thread.join()` would
    then block on forever."""
    monkeypatch.setenv("SDR_RX_DEVICES", "home:00000001")
    monkeypatch.setenv("SDR_RX_GAIN_DB", "42.5")
    seen_gain_db = []

    def fake_device(serial, gain_db=None, **kwargs):
        seen_gain_db.append(gain_db)
        raise RuntimeError("no SoapySDR bindings in this test")

    monkeypatch.setattr(sdr_rx, "SoapySDRDevice", fake_device)

    with pytest.raises(SystemExit):
        main()

    assert seen_gain_db == [42.5]


def test_main_defaults_gain_db_when_sdr_rx_gain_db_is_unset(monkeypatch):
    monkeypatch.setenv("SDR_RX_DEVICES", "home:00000001")
    monkeypatch.delenv("SDR_RX_GAIN_DB", raising=False)
    seen_gain_db = []

    def fake_device(serial, gain_db=None, **kwargs):
        seen_gain_db.append(gain_db)
        raise RuntimeError("no SoapySDR bindings in this test")

    monkeypatch.setattr(sdr_rx, "SoapySDRDevice", fake_device)

    with pytest.raises(SystemExit):
        main()

    assert seen_gain_db == [sdr_rx.DEFAULT_GAIN_DB]
