import pytest

from sdr_rx.prerequisites import (
    CONFLICTING_MODULE,
    ConflictingKernelModuleError,
    MissingUsbPassthroughError,
    assert_rtlsdr_module_not_loaded,
    assert_usb_bus_mapped,
)


def test_passes_when_module_not_in_proc_modules(tmp_path):
    proc_modules = tmp_path / "modules"
    proc_modules.write_text("usbcore 12345 0 - Live 0x0\n")
    assert_rtlsdr_module_not_loaded(proc_modules)


def test_raises_when_module_loaded(tmp_path):
    proc_modules = tmp_path / "modules"
    proc_modules.write_text(f"{CONFLICTING_MODULE} 20480 1 - Live 0x0\nusbcore 12345 0 - Live 0x0\n")
    with pytest.raises(ConflictingKernelModuleError, match=CONFLICTING_MODULE):
        assert_rtlsdr_module_not_loaded(proc_modules)


def test_does_not_match_module_name_as_a_substring(tmp_path):
    proc_modules = tmp_path / "modules"
    proc_modules.write_text(f"{CONFLICTING_MODULE}_other 20480 1 - Live 0x0\n")
    assert_rtlsdr_module_not_loaded(proc_modules)


def test_missing_proc_modules_does_not_raise(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert_rtlsdr_module_not_loaded(missing)


def test_usb_bus_present_passes(tmp_path):
    usb_bus = tmp_path / "usb"
    (usb_bus / "001").mkdir(parents=True)
    assert_usb_bus_mapped(usb_bus)


def test_usb_bus_present_but_empty_passes(tmp_path):
    """A host with the bus mapped but nothing plugged in is a valid state --
    the mapping is the whole /dev/bus/usb directory, so it stays a directory
    with no bus subdirectories rather than disappearing."""
    usb_bus = tmp_path / "usb"
    usb_bus.mkdir()
    assert_usb_bus_mapped(usb_bus)


def test_missing_usb_bus_raises_naming_the_compose_overlay(tmp_path):
    """The whole point of this check is that the librtlsdr errors it replaces
    don't mention compose at all -- so the message has to."""
    with pytest.raises(MissingUsbPassthroughError, match="compose.sdr.yaml"):
        assert_usb_bus_mapped(tmp_path / "does-not-exist")


def test_usb_bus_as_a_file_raises(tmp_path):
    usb_bus = tmp_path / "usb"
    usb_bus.write_text("not a directory")
    with pytest.raises(MissingUsbPassthroughError):
        assert_usb_bus_mapped(usb_bus)
