"""Per-channel RF health signal (design doc §3, "Health signal").

NWR broadcasts continuously, so silence on a channel doesn't mean "no
alerts" -- it means the RF path is dead (antenna, dongle, or transmitter
down). This is the primary liveness signal for the whole SDR path, so it has
to distinguish "quiet audio" from "no carrier at all."

Sampled continuously into TimescaleDB per the design doc, but the DB schema
and a real writer don't exist yet -- no service in this repo writes to
Postgres yet, and standing that up isn't a Phase-1 dependency. `HealthSink`
is the seam: `HealthTracker.sample()` computes the metric and hands it to
whatever sink is configured, so a TimescaleDB-backed one can be dropped in
later (Phase 5 storage) without touching this module.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import numpy as np

FLAT_CARRIER_SECONDS = 30.0
FLAT_CARRIER_RMS_THRESHOLD = 1e-4


@dataclass(frozen=True)
class ChannelHealth:
    channel: str
    timestamp_ns: int
    rms: float
    power: float
    dead: bool


class HealthSink(Protocol):
    def record(self, health: ChannelHealth) -> None: ...


class LoggingHealthSink:
    """Process-local default sink; stands in for the TimescaleDB writer."""

    def __init__(self):
        self.history: list[ChannelHealth] = []

    def record(self, health: ChannelHealth) -> None:
        self.history.append(health)


class HealthTracker:
    """Tracks per-channel flat-carrier duration across successive `sample()` calls."""

    def __init__(
        self,
        sink: HealthSink | None = None,
        flat_carrier_seconds: float = FLAT_CARRIER_SECONDS,
        rms_threshold: float = FLAT_CARRIER_RMS_THRESHOLD,
    ):
        self._sink = sink or LoggingHealthSink()
        self._flat_carrier_seconds = flat_carrier_seconds
        self._rms_threshold = rms_threshold
        self._flat_since: dict[str, float] = {}

    def sample(self, channel: str, audio: np.ndarray, now: float | None = None) -> ChannelHealth:
        now = time.monotonic() if now is None else now
        audio = np.asarray(audio, dtype=np.float64)
        rms = float(np.sqrt(np.mean(audio**2))) if audio.size else 0.0
        power = rms**2

        if rms < self._rms_threshold:
            self._flat_since.setdefault(channel, now)
        else:
            self._flat_since.pop(channel, None)

        flat_duration = now - self._flat_since[channel] if channel in self._flat_since else 0.0
        dead = flat_duration >= self._flat_carrier_seconds

        health = ChannelHealth(
            channel=channel, timestamp_ns=time.time_ns(), rms=rms, power=power, dead=dead
        )
        self._sink.record(health)
        return health
