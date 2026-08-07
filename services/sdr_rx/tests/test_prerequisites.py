import pytest

from sdr_rx.prerequisites import (
    CONFLICTING_MODULE,
    ConflictingKernelModuleError,
    assert_rtlsdr_module_not_loaded,
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
