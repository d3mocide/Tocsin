import pytest

import sdr_rx
from sdr_rx import main


@pytest.fixture(autouse=True)
def usb_bus_mapped(monkeypatch):
    """Stand in for the /dev/bus/usb passthrough check, which fails on any
    machine without USB mapped in -- including CI and this repo's dev sandbox.
    The check itself is covered in test_prerequisites.py; the tests below are
    about what main() does *after* it, so they'd otherwise all exit 1 early.
    Overridden by the two tests that exercise the check's own wiring."""
    monkeypatch.setattr(sdr_rx, "assert_usb_bus_mapped", lambda: None)


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


def test_main_fails_with_a_clear_message_when_the_usb_bus_is_not_mapped(monkeypatch, capsys):
    """The regression this guards: compose.sdr.yaml missing from COMPOSE_FILE
    left sdr-rx reporting `rtlsdr_get_index_by_serial(...) - -3`, which reads
    like a wrong serial. Fail before opening a device, naming the overlay."""
    monkeypatch.setenv("SDR_RX_DEVICES", "PDX:49435794")

    def unmapped():
        raise sdr_rx.MissingUsbPassthroughError("/dev/bus/usb ... add compose.sdr.yaml ...")

    monkeypatch.setattr(sdr_rx, "assert_usb_bus_mapped", unmapped)

    def fail_if_opened(serial, **kwargs):
        raise AssertionError("must not reach device construction with no USB bus")

    monkeypatch.setattr(sdr_rx, "SoapySDRDevice", fail_if_opened)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    assert "compose.sdr.yaml" in capsys.readouterr().err


def test_main_without_devices_does_not_require_the_usb_bus(monkeypatch, capsys):
    """`make dev-stack` runs the whole stack on a machine with no USB
    subsystem at all. sdr-rx must still reach its "no devices configured"
    exit 0 there -- entrypoint.sh stops retrying only on 0, so raising the
    bus error ahead of that check would crash-loop the container."""
    monkeypatch.delenv("SDR_RX_DEVICES", raising=False)

    def unmapped():
        raise sdr_rx.MissingUsbPassthroughError("no USB bus")

    monkeypatch.setattr(sdr_rx, "assert_usb_bus_mapped", unmapped)

    main()

    assert "no devices configured" in capsys.readouterr().out
