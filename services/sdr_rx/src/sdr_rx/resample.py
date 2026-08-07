"""Post-discriminator resampling to the two documented consumer rates.

Both ratios assume 50 kS/s real input -- the FM-discriminated output of
one channelizer bin -- per design doc §3, "Output contract".
"""

from __future__ import annotations

import numpy as np
from scipy.signal import resample_poly

BIN_RATE_HZ = 50_000
MULTIMON_RATE_HZ = 22_050
STT_RATE_HZ = 16_000


def to_multimon_rate(audio: np.ndarray) -> np.ndarray:
    """50 kS/s real audio -> 22050 Hz, for multimon-ng (`same_decoder`)."""
    return resample_poly(audio, 441, 1000)


def to_stt_rate(audio: np.ndarray) -> np.ndarray:
    """50 kS/s real audio -> 16000 Hz, for `stt_worker` and live audio."""
    return resample_poly(audio, 8, 25)


def to_s16le(audio: np.ndarray) -> np.ndarray:
    """Clip to [-1, 1] and convert to signed 16-bit PCM for the ZMQ output contract."""
    return (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
