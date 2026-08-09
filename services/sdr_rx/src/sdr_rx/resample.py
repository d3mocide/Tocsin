"""Post-discriminator resampling to the two documented consumer rates.

Both ratios assume 50 kS/s real input -- the FM-discriminated output of
one channelizer bin -- per design doc §3, "Output contract".
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from scipy.signal import firwin, resample_poly

BIN_RATE_HZ = 50_000
MULTIMON_RATE_HZ = 22_050
STT_RATE_HZ = 16_000


@lru_cache(maxsize=None)
def _resample_poly_filter(up: int, down: int, dtype: np.dtype = np.dtype(np.float64)) -> np.ndarray:
    """Precomputed anti-aliasing FIR taps for `resample_poly(x, up, down)`.

    Left to its defaults, `resample_poly` *redesigns* this filter --
    `firwin` plus a Kaiser window -- from scratch on every call, even though
    it only depends on `up`/`down`, which never change here. Profiled on a
    live pipeline (docs/design/tracking.md's 2026-08-09 entry): this
    redesign was over a third of `DevicePipeline.process()`'s total CPU
    time, dominated by the 441:1000 ratio's ~20,000-tap filter. Designing it
    once and passing it back in via `window=` (an array is accepted as
    literal filter taps, skipping the design step -- see
    `resample_poly`'s docstring) is a pure caching change with no numerical
    difference; `test_resample.py` asserts the cached path matches
    `resample_poly`'s own uncached default output exactly, so a future
    scipy version that changes this default formula fails loudly here
    rather than silently resampling differently.

    Replicates `resample_poly`'s internal filter-design formula (not part
    of its public API).
    """
    g = math.gcd(up, down)
    up, down = up // g, down // g
    max_rate = max(up, down)
    half_len = 10 * max_rate
    return firwin(2 * half_len + 1, 1.0 / max_rate, window=("kaiser", 5.0)).astype(dtype)


def _audio_dtype(audio: np.ndarray) -> np.dtype:
    """Taps are cached per dtype so float32 audio isn't promoted back to
    float64 by the filter alone (channelizer.py's "Sample precision")."""
    audio = np.asarray(audio)
    return audio.dtype if audio.dtype == np.float32 else np.dtype(np.float64)


def to_multimon_rate(audio: np.ndarray) -> np.ndarray:
    """50 kS/s real audio -> 22050 Hz, for multimon-ng (`same_decoder`)."""
    return resample_poly(audio, 441, 1000, window=_resample_poly_filter(441, 1000, _audio_dtype(audio)))


def to_stt_rate(audio: np.ndarray) -> np.ndarray:
    """50 kS/s real audio -> 16000 Hz, for `stt_worker` and live audio."""
    return resample_poly(audio, 8, 25, window=_resample_poly_filter(8, 25, _audio_dtype(audio)))


def to_s16le(audio: np.ndarray) -> np.ndarray:
    """Clip to [-1, 1] and convert to signed 16-bit PCM for the ZMQ output contract."""
    return (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
