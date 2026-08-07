import pytest

from sdr_rx.capture import DeviceConfig, SoapySDRDevice, parse_device_config


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
