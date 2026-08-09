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
import time
from pathlib import Path

from . import heartbeat as heartbeat_module
from .audio_conditioning import SQUELCH_OPEN_DB
from .bus import Publisher
from .capture import DEFAULT_GAIN_DB, SoapySDRDevice, enumerate_devices, parse_device_config
from .channels import nwr_bins
from .health import HealthTracker
from .pipeline import DevicePipeline
from .prerequisites import (
    ConflictingKernelModuleError,
    MissingUsbPassthroughError,
    assert_rtlsdr_module_not_loaded,
    assert_usb_bus_mapped,
)
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
            assert_usb_bus_mapped()
        except MissingUsbPassthroughError as exc:
            print(f"sdr-rx: {exc}", file=sys.stderr)
            sys.exit(1)
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

    # After the `not devices` return above, never before it: a hardware-free
    # dev stack (`make dev-stack`, no SDR_RX_DEVICES set) legitimately runs
    # with no USB bus mapped and must still exit 0 without retrying, the way
    # entrypoint.sh's sdr-rx loop expects. Once serials *are* configured, a
    # missing bus is a misconfiguration worth failing loudly on.
    try:
        assert_usb_bus_mapped()
    except MissingUsbPassthroughError as exc:
        print(f"sdr-rx: {exc}", file=sys.stderr)
        sys.exit(1)

    bind_addr = os.environ.get("SDR_RX_ZMQ_BIND", DEFAULT_ZMQ_BIND)
    ring_dir = Path(os.environ.get("SDR_RX_RING_BUFFER_DIR", str(DEFAULT_RING_BUFFER_DIR)))
    # Manual gain, not AGC (design doc §3: "Auto gain oscillates on a
    # constant carrier") -- 30 dB is a starting point for a typical
    # setup, not a universal value; antenna, cable loss, and distance to
    # the transmitter all shift what's correct for a given site.
    gain_db = float(os.environ.get("SDR_RX_GAIN_DB", DEFAULT_GAIN_DB))
    # Unlike gain, this squelch threshold is self-calibrating (see
    # audio_conditioning.py's module docstring) -- the default should work
    # across sites and dongles without retuning. Still overridable for a
    # site that wants a different quieting margin.
    squelch_open_db = float(os.environ.get("SDR_RX_SQUELCH_OPEN_DB", SQUELCH_OPEN_DB))
    # Same env var live_audio reads (LIVE_AUDIO_CHANNELS, not an SDR_RX_*
    # name -- both run in this one container, and this is what it's
    # gating: skip the STT-topic-only work below for a channel no consumer
    # of TOPIC_STT wants, rather than doing it and having live_audio throw
    # the result away). Empty/unset means "no filter" -- run it for every
    # channel, same as before this existed. SAME decode, the ring buffer,
    # and health stay on all seven regardless; see pipeline.py's docstring.
    raw_stt_channels = [c.strip().upper() for c in os.environ.get("LIVE_AUDIO_CHANNELS", "").split(",") if c.strip()]
    stt_channels = frozenset(raw_stt_channels) if raw_stt_channels else None
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
    started_sites: list[str] = []
    for device_config in devices:
        try:
            device = SoapySDRDevice(device_config.serial, gain_db=gain_db)
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
        pipeline = DevicePipeline(
            device_config.site,
            publisher,
            ring_buffers,
            health=health,
            spectrum=spectrum,
            squelch_open_db=squelch_open_db,
            stt_channels=stt_channels,
        )
        device.start()
        thread = threading.Thread(
            target=pipeline.run_forever, args=(device,), name=f"sdr-rx-{device_config.site}", daemon=True
        )
        thread.start()
        threads.append(thread)
        started_sites.append(device_config.site)

    if not threads:
        print("sdr-rx: no devices started successfully", file=sys.stderr)
        sys.exit(1)

    heartbeat = heartbeat_module.build(redis_client)
    if heartbeat is None:
        for thread in threads:
            thread.join()
        return

    # Beat from the main thread, watching the device threads, rather than
    # from inside DevicePipeline: a per-site capture thread that has
    # silently died is precisely what this needs to be able to report, and
    # a heartbeat living inside that thread would simply stop with it and
    # be indistinguishable from the whole process being gone.
    while any(thread.is_alive() for thread in threads):
        heartbeat.beat(
            sites=started_sites,
            devices_configured=len(devices),
            devices_running=sum(1 for thread in threads if thread.is_alive()),
        )
        time.sleep(1.0)
