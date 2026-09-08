"""SoapySDR device capture and multi-dongle serial addressing (design doc §3).

SoapySDR is only imported lazily, inside `SoapySDRDevice.__init__`, so
nothing else in this package -- or in the test suite -- has a hard
dependency on it being installed. It's only available on target hardware
with `soapysdr-module-rtlsdr` installed; see the README for bring-up.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from .channels import LO_HZ

SAMPLE_RATE_HZ = 1_200_000.0
DEFAULT_GAIN_DB = 30.0  # manual gain: AGC oscillates on a constant carrier (§3)
DEFAULT_CHUNK_SIZE = 65536
# IQ samples flow continuously at SAMPLE_RATE_HZ regardless of what's on
# air -- unlike audio, a silent channel never stops producing samples. A
# stall this long only happens when the USB transfer itself has died (e.g.
# librtlsdr's "cb transfer status: N, canceling..." after a bus hiccup),
# not when the channel goes quiet. See docs/design/tracking.md's
# 2026-09-08 entry: `readStream()` returning ret<=0 forever after a dead
# transfer used to be swallowed as an ordinary empty read, so the capture
# thread spun forever without ever exiting -- invisible to both the
# heartbeat (thread stayed "alive") and HealthTracker's flat-carrier
# watchdog (never called at all once reads went empty).
STALL_TIMEOUT_S = 5.0


class StreamDead(RuntimeError):
    """Raised by `read_chunk()` once the stream has produced no samples for
    longer than `STALL_TIMEOUT_S`. Callers should `reopen()` the device."""


@dataclass(frozen=True)
class DeviceConfig:
    """One physical dongle. Addressed by serial number, never by index --
    USB enumeration order isn't stable across reboots or replugs (§3). `site`
    names the antenna/transmitter-site a second dongle would cover (a second
    dongle is a second site, not additional channels: one dongle already
    covers all seven NWR channels)."""

    site: str
    serial: str


def parse_device_config(spec: str) -> list[DeviceConfig]:
    """Parse `"site:serial,site2:serial2"` into a list of DeviceConfig.

    An empty/whitespace-only spec returns an empty list -- the caller decides
    what "no devices configured" means (e.g. reporting a clear status
    instead of a stack trace).
    """
    spec = spec.strip()
    if not spec:
        return []
    configs: list[DeviceConfig] = []
    seen_serials: set[str] = set()
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise ValueError(f"invalid device spec {entry!r}, expected 'site:serial'")
        site, serial = entry.split(":", 1)
        site, serial = site.strip(), serial.strip()
        if not site or not serial:
            raise ValueError(f"invalid device spec {entry!r}, expected 'site:serial'")
        if serial in seen_serials:
            raise ValueError(f"duplicate serial {serial!r} in device spec {spec!r}")
        seen_serials.add(serial)
        configs.append(DeviceConfig(site=site, serial=serial))
    return configs


def enumerate_devices() -> list[dict[str, str]]:
    """List every rtlsdr device SoapySDR can currently see, so a serial can
    be discovered for `SDR_RX_DEVICES` without guessing (§3: addressed by
    serial, never index)."""
    try:
        import SoapySDR
    except ImportError as exc:
        raise RuntimeError(
            "SoapySDR python bindings are not installed. Device enumeration only runs on "
            "target hardware with soapysdr-module-rtlsdr installed -- see "
            "services/sdr_rx/README.md."
        ) from exc
    return [dict(result) for result in SoapySDR.Device.enumerate({"driver": "rtlsdr"})]


class SoapySDRDevice:
    """One open RTL-SDR device stream, addressed by serial number.

    Exposes `read_chunk()` so it satisfies the same informal SampleSource
    interface `DevicePipeline` (see pipeline.py) accepts from synthetic
    sources in tests.
    """

    def __init__(
        self,
        serial: str,
        frequency_hz: float = LO_HZ,
        sample_rate_hz: float = SAMPLE_RATE_HZ,
        gain_db: float = DEFAULT_GAIN_DB,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ):
        try:
            import SoapySDR  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "SoapySDR python bindings are not installed. SoapySDRDevice only runs on "
                "target hardware with soapysdr-module-rtlsdr installed -- see "
                "services/sdr_rx/README.md."
            ) from exc

        self.serial = serial
        self.chunk_size = chunk_size
        self._frequency_hz = frequency_hz
        self._sample_rate_hz = sample_rate_hz
        self._gain_db = gain_db
        self._open()

    def _open(self) -> None:
        import SoapySDR
        from SoapySDR import SOAPY_SDR_CF32, SOAPY_SDR_RX

        self._device = SoapySDR.Device({"driver": "rtlsdr", "serial": self.serial})
        self._device.setSampleRate(SOAPY_SDR_RX, 0, self._sample_rate_hz)
        self._device.setFrequency(SOAPY_SDR_RX, 0, self._frequency_hz)
        self._device.setGainMode(SOAPY_SDR_RX, 0, False)
        self._device.setGain(SOAPY_SDR_RX, 0, self._gain_db)
        self._stream = self._device.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
        self._last_data_at = time.monotonic()

    def start(self) -> None:
        self._device.activateStream(self._stream)

    def stop(self) -> None:
        self._device.deactivateStream(self._stream)
        self._device.closeStream(self._stream)

    def reopen(self) -> None:
        """Recover from a dead USB transfer (`StreamDead`) by closing and
        reopening the device and stream in place, then restarting it --
        cheaper and faster than exiting the process and paying entrypoint.sh's
        full `uv run` + SoapySDR re-init on every USB hiccup."""
        try:
            self.stop()
        except Exception:
            pass  # already broken -- nothing clean to release
        self._open()
        self.start()

    def read_chunk(self) -> np.ndarray:
        buf = np.empty(self.chunk_size, dtype=np.complex64)
        result = self._device.readStream(self._stream, [buf], self.chunk_size)
        if result.ret <= 0:
            if time.monotonic() - self._last_data_at >= STALL_TIMEOUT_S:
                raise StreamDead(
                    f"{self.serial}: no samples for >{STALL_TIMEOUT_S}s "
                    f"(last readStream ret={result.ret})"
                )
            return np.zeros(0, dtype=np.complex64)
        self._last_data_at = time.monotonic()
        return buf[: result.ret]
