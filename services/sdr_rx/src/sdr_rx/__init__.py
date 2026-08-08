"""sdr-rx entrypoint: host checks, device construction from env, capture loop.

The channelizer and every stage that doesn't need a physical dongle (ZMQ
publisher, tmpfs ring buffer, health signal, device-config parsing) is
proven by unit tests. SoapySDR device I/O itself only runs on target
hardware -- if none is configured or the bindings aren't installed, this
reports why and exits cleanly rather than pretending to run a capture
pipeline that isn't there.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from .bus import Publisher
from .capture import SoapySDRDevice, enumerate_devices, parse_device_config
from .channels import nwr_bins
from .health import HealthTracker
from .pipeline import DevicePipeline
from .prerequisites import ConflictingKernelModuleError, assert_rtlsdr_module_not_loaded
from .ring_buffer import ChannelRingBuffer

DEFAULT_ZMQ_BIND = "tcp://0.0.0.0:5555"
DEFAULT_RING_BUFFER_DIR = Path("/tmp/sdr_rx_ring")


def main() -> None:
    try:
        assert_rtlsdr_module_not_loaded()
    except ConflictingKernelModuleError as exc:
        print(f"sdr-rx: {exc}", file=sys.stderr)
        sys.exit(1)

    if os.environ.get("SDR_RX_LIST_DEVICES"):
        try:
            found = enumerate_devices()
        except RuntimeError as exc:
            print(f"sdr-rx: {exc}", file=sys.stderr)
            sys.exit(1)
        if not found:
            print("sdr-rx: no rtlsdr devices found")
            return
        print("sdr-rx: found devices (use the serial in SDR_RX_DEVICES='site:serial,...'):")
        for kwargs in found:
            print(f"  serial={kwargs.get('serial', '?')} label={kwargs.get('label', '?')}")
        return

    devices = parse_device_config(os.environ.get("SDR_RX_DEVICES", ""))
    if not devices:
        print(
            "sdr-rx: no devices configured (set SDR_RX_DEVICES='site:serial,...'). "
            "channelizer, ZMQ publisher, ring buffer, and health signal are implemented "
            "and unit-tested; device capture requires target RTL-SDR hardware -- see "
            "services/sdr_rx/README.md."
        )
        return

    bind_addr = os.environ.get("SDR_RX_ZMQ_BIND", DEFAULT_ZMQ_BIND)
    ring_dir = Path(os.environ.get("SDR_RX_RING_BUFFER_DIR", str(DEFAULT_RING_BUFFER_DIR)))
    publisher = Publisher(bind_addr)
    health = HealthTracker()

    threads: list[threading.Thread] = []
    for device_config in devices:
        try:
            device = SoapySDRDevice(device_config.serial)
        except RuntimeError as exc:
            print(f"sdr-rx: site {device_config.site!r} ({device_config.serial}): {exc}", file=sys.stderr)
            continue

        ring_buffers = {
            b.channel: ChannelRingBuffer(ring_dir / device_config.site, b.channel) for b in nwr_bins()
        }
        pipeline = DevicePipeline(device_config.site, publisher, ring_buffers, health=health)
        device.start()
        thread = threading.Thread(
            target=pipeline.run_forever, args=(device,), name=f"sdr-rx-{device_config.site}", daemon=True
        )
        thread.start()
        threads.append(thread)

    if not threads:
        print("sdr-rx: no devices started successfully", file=sys.stderr)
        sys.exit(1)

    for thread in threads:
        thread.join()
