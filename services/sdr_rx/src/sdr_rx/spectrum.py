"""The 41 spectrum-only bins (design doc §3: "All 48 bins are computed
(the FFT costs the same either way). The 41 unused bins feed the
spectrum/waterfall display as free occupancy data.") -- genuinely free:
`PolyphaseChannelizer.process()` already produces all 48 bins every
frame, and `DevicePipeline.process()` already has that array in hand; this
just reads the 41 `all_bins()` doesn't discriminate into an NWR channel,
instead of discarding them.

Published as a single latest-snapshot Redis key (`redis_sink.py`'s
`RedisSpectrumSink`, plain `SET`), not a stream -- a waterfall/spectrum
display only ever wants "right now," never a history to replay, so
there's no correctness reason to pay for stream durability or
consumer-group bookkeeping here the way `tocsin:alerts`/`tocsin:health`
warrant.

One `SpectrumTracker` per site, not shared like `HealthTracker` -- each
site's dongle has its own independent 48-bin spectrum; averaging two
sites' bins together into one snapshot would just be wrong, not merely
imprecise.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .channels import NUM_BINS, all_bins

DEFAULT_PUBLISH_INTERVAL_SECONDS = 1.0
_MIN_MAGNITUDE = 1e-12  # floor before log10, avoids -inf on true silence


@dataclass(frozen=True)
class SpectrumSnapshot:
    site: str
    timestamp_ns: int
    bin_frequencies_hz: tuple[float, ...]
    bin_power_db: tuple[float, ...]


class SpectrumSink(Protocol):
    def record(self, snapshot: SpectrumSnapshot) -> None: ...


class LoggingSpectrumSink:
    def __init__(self):
        self.history: list[SpectrumSnapshot] = []

    def record(self, snapshot: SpectrumSnapshot) -> None:
        self.history.append(snapshot)


class SpectrumTracker:
    """Cheap to call every `process()` frame -- throttling happens inside
    `sample()`, not by the caller deciding when to call it, so
    `DevicePipeline` doesn't need its own clock/interval logic."""

    def __init__(
        self,
        site: str,
        sink: SpectrumSink | None = None,
        publish_interval_seconds: float = DEFAULT_PUBLISH_INTERVAL_SECONDS,
        now_fn=time.monotonic,
    ):
        self._site = site
        self._sink = sink or LoggingSpectrumSink()
        self._publish_interval_seconds = publish_interval_seconds
        self._now = now_fn
        self._last_published: float | None = None
        self._bins = all_bins()

    def sample(self, spectrum: np.ndarray) -> None:
        """`spectrum`: `(n_frames, 48)` complex array straight from
        `PolyphaseChannelizer.process()`, indexed by raw FFT column (0..47),
        *not* by odd-stacked bin index `k` -- same `k % NUM_BINS` mapping
        `DevicePipeline.process()` already uses per-NWR-bin, applied here
        across all 48 so `bin_power_db` lines up with `bin_frequencies_hz`
        (in turn `all_bins()`'s k-ordering, -24..23)."""
        now = self._now()
        if self._last_published is not None and now - self._last_published < self._publish_interval_seconds:
            return
        self._last_published = now

        magnitude_by_column = np.mean(np.abs(spectrum), axis=0)  # (48,), raw FFT column order
        power_db_by_column = 20.0 * np.log10(np.maximum(magnitude_by_column, _MIN_MAGNITUDE))
        power_db = [float(power_db_by_column[b.k % NUM_BINS]) for b in self._bins]

        self._sink.record(
            SpectrumSnapshot(
                site=self._site,
                timestamp_ns=time.time_ns(),
                bin_frequencies_hz=tuple(b.frequency_hz for b in self._bins),
                bin_power_db=tuple(power_db),
            )
        )
