import pytest

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
