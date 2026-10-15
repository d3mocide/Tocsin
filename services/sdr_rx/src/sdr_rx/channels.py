"""NWR channel grid: bin index <-> frequency <-> channel name.

The tuner LO sits on a bin *edge* (162.4875 MHz), so bin centers land at
LO + (k + 0.5) * 25 kHz for k in -NUM_BINS/2 .. NUM_BINS/2 - 1. The seven NOAA Weather Radio
channels occupy k = -4..2; the remaining bins (41 of 48 by default) are spectrum-only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

LO_HZ = 162_487_500.0
CHANNEL_SPACING_HZ = 25_000.0
# RTL-SDR dongles only run at 225.001-300 kS/s or 0.900001-3.2 MS/s (librtlsdr's gap is real: asking for a rate
# in between gets silently adjusted).
_RTL_RATE_RANGES = ((225_001.0, 300_000.0), (900_001.0, 3_200_000.0))


def validate_num_bins(num_bins: int) -> int:
    """The channelizer has one bin per 25 kHz of sample rate, so the bin count fixes the dongle's sample rate.
    It must be even (2x oversampling), wide enough to hold the seven weather channels (k = -4..2), and give a
    rate the RTL-SDR actually supports."""
    rate = num_bins * CHANNEL_SPACING_HZ
    if num_bins % 2 or num_bins < 8 or not any(lo <= rate <= hi for lo, hi in _RTL_RATE_RANGES):
        raise ValueError(
            f"SDR_RX_NUM_BINS={num_bins} gives {rate / 1e3:.0f} kS/s; use 12 (300 kS/s, weather channels only) "
            "or a value giving 900 kS/s-3.2 MS/s such as 48 (1.2 MS/s, full spectrum view)"
        )
    return num_bins


# 48 keeps the full-spectrum design (41 spectrum-only bins for the waterfall) and is what the unit tests pin.
# 12 computes the seven weather channels with five spare bins at a quarter of the sample rate -- about a fifth
# of the CPU for the same 50 kHz per-channel output. Deployments pick with SDR_RX_NUM_BINS (compose sets 12).
NUM_BINS = validate_num_bins(int(os.environ.get("SDR_RX_NUM_BINS", "48")))

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


def all_bins(num_bins: int = NUM_BINS) -> list[Bin]:
    half = num_bins // 2
    bins = []
    for k in range(-half, half):
        bins.append(Bin(k=k, frequency_hz=bin_frequency_hz(k), channel=NWR_CHANNEL_NAMES.get(k)))
    return bins


def nwr_bins() -> list[Bin]:
    return [b for b in all_bins() if b.channel is not None]
