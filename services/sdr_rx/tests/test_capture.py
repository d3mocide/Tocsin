import sys
import types

import pytest

from sdr_rx import capture
from sdr_rx.capture import DeviceConfig, SoapySDRDevice, StreamDead, enumerate_devices, parse_device_config


def test_parses_single_device():
    assert parse_device_config("site-a:1234") == [DeviceConfig(site="site-a", serial="1234")]


def test_parses_multiple_devices():
    assert parse_device_config("site-a:1234,site-b:5678") == [
        DeviceConfig(site="site-a", serial="1234"),
        DeviceConfig(site="site-b", serial="5678"),
    ]


def test_strips_whitespace_around_entries():
    assert parse_device_config(" site-a : 1234 , site-b:5678 ") == [
        DeviceConfig(site="site-a", serial="1234"),
        DeviceConfig(site="site-b", serial="5678"),
    ]


def test_empty_spec_returns_empty_list():
    assert parse_device_config("") == []
    assert parse_device_config("   ") == []


def test_rejects_entry_without_colon():
    with pytest.raises(ValueError):
        parse_device_config("no-colon-here")


def test_rejects_empty_site_or_serial():
    with pytest.raises(ValueError):
        parse_device_config(":1234")
    with pytest.raises(ValueError):
        parse_device_config("site-a:")


def test_rejects_duplicate_serial():
    with pytest.raises(ValueError):
        parse_device_config("site-a:1234,site-b:1234")


def test_soapysdr_device_reports_missing_bindings_clearly():
    with pytest.raises(RuntimeError, match="SoapySDR"):
        SoapySDRDevice(serial="00000001")


def test_enumerate_devices_reports_missing_bindings_clearly():
    with pytest.raises(RuntimeError, match="SoapySDR"):
        enumerate_devices()


class _FakeSoapyDevice:
    """Stands in for `SoapySDR.Device` -- controls what `readStream()`
    returns so `SoapySDRDevice`'s stall-detection/reopen logic (capture.py)
    is exercisable without real RTL-SDR hardware."""

    instances: list["_FakeSoapyDevice"] = []

    def __init__(self, args):
        self.args = args
        self.read_ret = 1  # >0 by default: "samples available"
        self.open_count = 1
        self.activated = False
        self.closed = False
        _FakeSoapyDevice.instances.append(self)

    def setSampleRate(self, *a):
        pass

    def setFrequency(self, *a):
        pass

    def setGainMode(self, *a):
        pass

    def setGain(self, *a):
        pass

    def setupStream(self, *a):
        return object()

    def activateStream(self, stream):
        self.activated = True

    def deactivateStream(self, stream):
        self.activated = False

    def closeStream(self, stream):
        self.closed = True

    def readStream(self, stream, bufs, n):
        return types.SimpleNamespace(ret=self.read_ret)


def _install_fake_soapysdr(monkeypatch):
    _FakeSoapyDevice.instances = []
    fake_module = types.SimpleNamespace(Device=_FakeSoapyDevice, SOAPY_SDR_CF32=1, SOAPY_SDR_RX=0)
    monkeypatch.setitem(sys.modules, "SoapySDR", fake_module)
    return fake_module


def _fake_clock(monkeypatch, start=0.0):
    clock = {"t": start}
    monkeypatch.setattr(capture.time, "monotonic", lambda: clock["t"])
    return clock


def test_read_chunk_returns_data_when_stream_is_healthy(monkeypatch):
    _install_fake_soapysdr(monkeypatch)
    _fake_clock(monkeypatch)
    device = SoapySDRDevice(serial="00000001")
    chunk = device.read_chunk()
    assert chunk.size == 1  # fake readStream reports ret=1 sample available


def test_read_chunk_returns_empty_on_a_read_within_the_stall_window(monkeypatch):
    _install_fake_soapysdr(monkeypatch)
    clock = _fake_clock(monkeypatch)
    device = SoapySDRDevice(serial="00000001")
    _FakeSoapyDevice.instances[0].read_ret = 0
    clock["t"] += capture.STALL_TIMEOUT_S - 0.1
    assert device.read_chunk().size == 0


def test_read_chunk_raises_stream_dead_once_stall_timeout_elapses(monkeypatch):
    _install_fake_soapysdr(monkeypatch)
    clock = _fake_clock(monkeypatch)
    device = SoapySDRDevice(serial="00000001")
    _FakeSoapyDevice.instances[0].read_ret = 0
    clock["t"] += capture.STALL_TIMEOUT_S + 0.1
    with pytest.raises(StreamDead, match="00000001"):
        device.read_chunk()


def test_a_good_read_resets_the_stall_clock(monkeypatch):
    _install_fake_soapysdr(monkeypatch)
    clock = _fake_clock(monkeypatch)
    device = SoapySDRDevice(serial="00000001")
    fake = _FakeSoapyDevice.instances[0]

    clock["t"] += capture.STALL_TIMEOUT_S - 0.1
    fake.read_ret = 1
    assert device.read_chunk().size > 0  # good read resets the clock

    fake.read_ret = 0
    clock["t"] += capture.STALL_TIMEOUT_S - 0.1
    assert device.read_chunk().size == 0  # not yet stalled again


def test_reopen_closes_and_recreates_the_device_and_restarts_it(monkeypatch):
    _install_fake_soapysdr(monkeypatch)
    _fake_clock(monkeypatch)
    device = SoapySDRDevice(serial="00000001")
    device.start()
    original = _FakeSoapyDevice.instances[0]
    assert original.activated is True

    device.reopen()

    assert original.closed is True
    assert len(_FakeSoapyDevice.instances) == 2
    reopened = _FakeSoapyDevice.instances[1]
    assert reopened.activated is True
    # the stall clock should be reset by the reopen, not carried over
    reopened.read_ret = 0
    assert device.read_chunk().size == 0
