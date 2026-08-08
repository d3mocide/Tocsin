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
from .spectrum import SpectrumTracker

DEFAULT_ZMQ_BIND = "tcp://0.0.0.0:5555"
DEFAULT_RING_BUFFER_DIR = Path("/tmp/sdr_rx_ring")


def _build_redis_client():
    """`None` when `SDR_RX_REDIS_URL` isn't set -- health/spectrum then
    fall back to their in-process default sinks (`LoggingHealthSink`/
    `LoggingSpectrumSink`), same optional-Redis seam every other service
    in this repo uses."""
    redis_url = os.environ.get("SDR_RX_REDIS_URL")
    if not redis_url:
        return None
    import redis as redis_lib

    return redis_lib.from_url(redis_url)


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

    raw_devices = os.environ.get("SDR_RX_DEVICES", "")
    try:
        devices = parse_device_config(raw_devices)
    except ValueError as exc:
        print(
            f"sdr-rx: bad SDR_RX_DEVICES={raw_devices!r}: {exc}. "
            "Expected 'site:serial,site2:serial2', e.g. SDR_RX_DEVICES=home:00000001 "
            "-- run 'make sdr-devices' to find a dongle's serial.",
            file=sys.stderr,
        )
        sys.exit(1)
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

    redis_client = _build_redis_client()
    health_sink = None
    if redis_client is not None:
        from .redis_sink import RedisStreamHealthSink

        health_sink = RedisStreamHealthSink(redis_client)
    # One HealthTracker shared across every site -- safe now that it keys
    # on (site, channel), not channel alone (see health.py's docstring).
    health = HealthTracker(sink=health_sink)

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
        spectrum_sink = None
        if redis_client is not None:
            from .redis_sink import RedisSpectrumSink

            spectrum_sink = RedisSpectrumSink(redis_client)
        # One SpectrumTracker per site, unlike health -- each site's dongle
        # has its own independent 48-bin spectrum (spectrum.py's docstring).
        spectrum = SpectrumTracker(device_config.site, sink=spectrum_sink)
        pipeline = DevicePipeline(device_config.site, publisher, ring_buffers, health=health, spectrum=spectrum)
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
