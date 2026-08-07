"""NWR channel grid: bin index <-> frequency <-> channel name.

The tuner LO sits on a bin *edge* (162.4875 MHz), so bin centers land at
LO + (k + 0.5) * 25 kHz for k in -24..23. The seven NOAA Weather Radio
channels occupy k = -4..2; the remaining 41 bins are spectrum-only.
"""

from __future__ import annotations

from dataclasses import dataclass

LO_HZ = 162_487_500.0
CHANNEL_SPACING_HZ = 25_000.0
NUM_BINS = 48

NWR_CHANNEL_NAMES = {
    -4: "WX1",
    -3: "WX2",
    -2: "WX3",
    -1: "WX4",
    0: "WX5",
    1: "WX6",
    2: "WX7",
}


@dataclass(frozen=True)
class Bin:
    k: int
    frequency_hz: float
    channel: str | None


def bin_frequency_hz(k: int) -> float:
    """Center frequency of odd-stacked bin k (k=0 is the bin containing LO + half a channel)."""
    return LO_HZ + (k + 0.5) * CHANNEL_SPACING_HZ


def bin_index_for_frequency(frequency_hz: float) -> int:
    """Inverse of bin_frequency_hz, rounded to the nearest bin."""
    return round((frequency_hz - LO_HZ) / CHANNEL_SPACING_HZ - 0.5)


def all_bins() -> list[Bin]:
    half = NUM_BINS // 2
    bins = []
    for k in range(-half, half):
        bins.append(Bin(k=k, frequency_hz=bin_frequency_hz(k), channel=NWR_CHANNEL_NAMES.get(k)))
    return bins


def nwr_bins() -> list[Bin]:
    return [b for b in all_bins() if b.channel is not None]
