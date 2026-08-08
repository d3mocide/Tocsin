"""Host prerequisite checks (design doc §3, "Host prerequisite").

`dvb_usb_rtl28xxu` must be blacklisted on the *host*, not the container -- if
the kernel DVB driver claims the RTL-SDR dongle first, SoapySDR never sees
it. Kernel module state is host-global and shows up in /proc/modules the
same way from inside a container, since modules aren't namespaced, so this
check runs unmodified in either place.
"""

from __future__ import annotations

from pathlib import Path

CONFLICTING_MODULE = "dvb_usb_rtl28xxu"
PROC_MODULES_PATH = Path("/proc/modules")


class ConflictingKernelModuleError(RuntimeError):
    pass


def assert_rtlsdr_module_not_loaded(proc_modules_path: Path = PROC_MODULES_PATH) -> None:
    """Raise ConflictingKernelModuleError if the DVB RTL driver is loaded.

    A missing /proc/modules (non-Linux dev machine, restricted sandbox) is
    not a failure -- the check just can't run there, so it's skipped rather
    than raised.
    """
    if not proc_modules_path.exists():
        return
    for line in proc_modules_path.read_text().splitlines():
        if not line:
            continue
        name = line.split(maxsplit=1)[0]
        if name == CONFLICTING_MODULE:
            raise ConflictingKernelModuleError(
                f"kernel module '{CONFLICTING_MODULE}' is loaded -- it claims the RTL-SDR "
                "dongle before SoapySDR can see it. Blacklist it on the HOST (not the "
                f"container): add 'blacklist {CONFLICTING_MODULE}' to "
                f"/etc/modprobe.d/blacklist-rtlsdr.conf, then `sudo rmmod {CONFLICTING_MODULE}` "
                "or reboot. See services/sdr_rx/README.md."
            )
