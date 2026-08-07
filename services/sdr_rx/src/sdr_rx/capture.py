"""SoapySDR device capture and multi-dongle serial addressing (design doc §3).

SoapySDR is only imported lazily, inside `SoapySDRDevice.__init__`, so
nothing else in this package -- or in the test suite -- has a hard
dependency on it being installed. It's only available on target hardware
with `soapysdr-module-rtlsdr` installed; see the README for bring-up.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .channels import LO_HZ

SAMPLE_RATE_HZ = 1_200_000.0
DEFAULT_GAIN_DB = 30.0  # manual gain: AGC oscillates on a constant carrier (§3)
DEFAULT_CHUNK_SIZE = 65536


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
            import SoapySDR
            from SoapySDR import SOAPY_SDR_CF32, SOAPY_SDR_RX
        except ImportError as exc:
            raise RuntimeError(
                "SoapySDR python bindings are not installed. SoapySDRDevice only runs on "
                "target hardware with soapysdr-module-rtlsdr installed -- see "
                "services/sdr_rx/README.md."
            ) from exc

        self.serial = serial
        self.chunk_size = chunk_size
        self._device = SoapySDR.Device({"driver": "rtlsdr", "serial": serial})
        self._device.setSampleRate(SOAPY_SDR_RX, 0, sample_rate_hz)
        self._device.setFrequency(SOAPY_SDR_RX, 0, frequency_hz)
        self._device.setGainMode(SOAPY_SDR_RX, 0, False)
        self._device.setGain(SOAPY_SDR_RX, 0, gain_db)
        self._stream = self._device.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)

    def start(self) -> None:
        self._device.activateStream(self._stream)

    def stop(self) -> None:
        self._device.deactivateStream(self._stream)
        self._device.closeStream(self._stream)

    def read_chunk(self) -> np.ndarray:
        buf = np.empty(self.chunk_size, dtype=np.complex64)
        result = self._device.readStream(self._stream, [buf], self.chunk_size)
        if result.ret <= 0:
            return np.zeros(0, dtype=np.complex64)
        return buf[: result.ret]
