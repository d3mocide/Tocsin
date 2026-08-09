"""Host prerequisite checks (design doc §3, "Host prerequisite").

`dvb_usb_rtl28xxu` must be blacklisted on the *host*, not the container -- if
the kernel DVB driver claims the RTL-SDR dongle first, SoapySDR never sees
it. Kernel module state is host-global and shows up in /proc/modules the
same way from inside a container, since modules aren't namespaced, so this
check runs unmodified in either place.

The second check here is container-side: the host USB bus has to actually be
mapped in before any of the above matters.
"""

from __future__ import annotations

from pathlib import Path

CONFLICTING_MODULE = "dvb_usb_rtl28xxu"
PROC_MODULES_PATH = Path("/proc/modules")
USB_BUS_PATH = Path("/dev/bus/usb")


class ConflictingKernelModuleError(RuntimeError):
    pass


class MissingUsbPassthroughError(RuntimeError):
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


def assert_usb_bus_mapped(usb_bus_path: Path = USB_BUS_PATH) -> None:
    """Raise MissingUsbPassthroughError if the host USB bus isn't mapped in.

    Docker's default /dev has no `bus/` at all, so this directory exists only
    because compose.sdr.yaml mapped it. Without it libusb still *counts* the
    dongles but can't open any of them, and librtlsdr degrades into
    `rtlsdr_get_device_usb_strings(N) failed` for every device plus
    `rtlsdr_get_index_by_serial() - -3` -- which reads like a wrong serial in
    SDR_RX_DEVICES and sends you looking at the udev rule, not at the compose
    file that's actually missing. Checking the mount point first turns that
    into one message naming the real cause.
    """
    if usb_bus_path.is_dir():
        return
    raise MissingUsbPassthroughError(
        f"{usb_bus_path} is not present in this container -- the RTL-SDR USB passthrough "
        "isn't mapped, so librtlsdr can see the dongles but cannot open any of them. Add "
        "compose.sdr.yaml to COMPOSE_FILE in .env "
        "(COMPOSE_FILE=compose.yaml:compose.sdr.yaml:compose.mesh.yaml), or start the stack "
        "with `make up-offgrid`/`make up-hybrid`, which add it for you. `make dev-stack` is "
        "the hardware-free path and does not set SDR_RX_DEVICES. See services/sdr_rx/README.md."
    )
