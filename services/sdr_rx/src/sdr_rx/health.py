"""Per-channel RF health signal (design doc §3, "Health signal").

NWR broadcasts continuously, so silence on a channel doesn't mean "no
alerts" -- it means the RF path is dead (antenna, dongle, or transmitter
down). This is the primary liveness signal for the whole SDR path, so it has
to distinguish "quiet audio" from "no carrier at all."

Keyed on `(site, channel)`, not `channel` alone -- a second dongle is a
second transmitter *site* covering the same seven channel names (design
doc §3, "Multi-dongle"), the same reason `sdr_rx.bus`'s ZMQ topics carry
site (see `docs/design/tracking.md`'s 2026-08-07 session log for that
exact bug already being found and fixed once for topics). This module
predates that fix and shared one `HealthTracker` across every site's
`DevicePipeline` with no site key at all -- two sites' `WX5` would
silently collide in `_flat_since` and in every emitted `ChannelHealth`,
with no way for a consumer to tell which site's channel had actually gone
dead. Fixed here, ahead of Phase 8 actually surfacing this data in a UI
(`docs/design/tracking.md`).

Sampled continuously into TimescaleDB per the design doc, via
`RedisStreamHealthSink` (Phase 8) -- `HealthSink` is the seam:
`HealthTracker.sample()` computes the metric and hands it to whatever sink
is configured.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import numpy as np

FLAT_CARRIER_SECONDS = 30.0
FLAT_CARRIER_RMS_THRESHOLD = 1e-4
# `sample()` is called once per channel per capture chunk (~55ms at the
# design's 1.2 MS/s / 65,536-sample chunk size -- see capture.py), so
# reporting every call means ~128 Redis XADDs/sec for a single seven-channel
# dongle, each one round-tripping through `api`'s consumer into a Postgres
# INSERT and an SSE broadcast to every connected browser. None of that
# granularity does anything for this signal's actual job -- detecting a
# carrier flat for FLAT_CARRIER_SECONDS (30s) -- so the sink report is
# throttled to this interval while the flat-carrier state itself still
# updates on every single call (in-process, no I/O, effectively free).
# Profiled on a live deployment: this was a real, measurable contributor to
# `api`/`postgres` CPU (docs/design/tracking.md's entry this date).
DEFAULT_REPORT_INTERVAL_S = 1.0


@dataclass(frozen=True)
class ChannelHealth:
    site: str
    channel: str
    timestamp_ns: int
    rms: float
    power: float
    dead: bool


class HealthSink(Protocol):
    def record(self, health: ChannelHealth) -> None: ...


class LoggingHealthSink:
    """Process-local default sink; stands in for `RedisStreamHealthSink`
    when no Redis URL is configured (local/test runs)."""

    def __init__(self):
        self.history: list[ChannelHealth] = []

    def record(self, health: ChannelHealth) -> None:
        self.history.append(health)


class HealthTracker:
    """Tracks per-`(site, channel)` flat-carrier duration across successive
    `sample()` calls. One instance is safe to share across every site's
    `DevicePipeline` (unlike `SpectrumTracker`, which is one-per-site) --
    the `(site, channel)` key is what makes that safe now."""

    def __init__(
        self,
        sink: HealthSink | None = None,
        flat_carrier_seconds: float = FLAT_CARRIER_SECONDS,
        rms_threshold: float = FLAT_CARRIER_RMS_THRESHOLD,
        report_interval_s: float = DEFAULT_REPORT_INTERVAL_S,
    ):
        self._sink = sink or LoggingHealthSink()
        self._flat_carrier_seconds = flat_carrier_seconds
        self._rms_threshold = rms_threshold
        self._report_interval_s = report_interval_s
        self._flat_since: dict[tuple[str, str], float] = {}
        self._last_reported_at: dict[tuple[str, str], float] = {}

    def sample(self, site: str, channel: str, audio: np.ndarray, now: float | None = None) -> ChannelHealth:
        now = time.monotonic() if now is None else now
        key = (site, channel)
        audio = np.asarray(audio, dtype=np.float64)
        rms = float(np.sqrt(np.mean(audio**2))) if audio.size else 0.0
        power = rms**2

        if rms < self._rms_threshold:
            self._flat_since.setdefault(key, now)
        else:
            self._flat_since.pop(key, None)

        flat_duration = now - self._flat_since[key] if key in self._flat_since else 0.0
        dead = flat_duration >= self._flat_carrier_seconds

        health = ChannelHealth(
            site=site, channel=channel, timestamp_ns=time.time_ns(), rms=rms, power=power, dead=dead
        )
        last_reported = self._last_reported_at.get(key)
        if last_reported is None or now - last_reported >= self._report_interval_s:
            self._sink.record(health)
            self._last_reported_at[key] = now
        return health
