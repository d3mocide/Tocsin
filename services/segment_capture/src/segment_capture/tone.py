"""1050 Hz attention-tone-end detection (design doc §4's message
structure: `[SAME header x3] -> [1050 Hz tone, 8-11s] -> [voice] -> [NNNN
EOM x3]`).

`segment_capture` doesn't trim the tone itself -- design doc §4 says it
emits "a WAV artifact plus timing metadata", full segment included, for
logging -- this just locates the boundary `stt_worker` later cuts at
before inference (design doc §6's first preprocessing step; skipping it is
called out there as the difference between a real transcript and
confidently-worded garbage fed straight to a mesh broadcast).

Detection: split the segment into fixed windows and compute each window's
energy at 1050 Hz as a fraction of its total energy -- a single-frequency
DFT correlation, which is mathematically the same result a streaming
Goertzel filter would give for a fixed window, just simpler to vectorize
with numpy over audio that's already fully buffered rather than arriving
live. SAME's own AFSK header tones (~1562.5/2083.3 Hz) and NWR voice audio
both have LOW 1050 Hz energy fraction, so only the attention tone itself
produces a long contiguous run of high-fraction windows; voice_start is
the end of the longest such run.
"""

from __future__ import annotations

import numpy as np

TONE_HZ = 1050.0
WINDOW_SECONDS = 0.1
MIN_TONE_SECONDS = 5.0  # true tone is 8-11s; require most of that to count as real
ENERGY_FRACTION_THRESHOLD = 0.5


def _tone_energy_fraction(window: np.ndarray, sample_rate_hz: float) -> float:
    n = len(window)
    if n == 0:
        return 0.0
    t = np.arange(n) / sample_rate_hz
    cos_corr = np.dot(window, np.cos(2 * np.pi * TONE_HZ * t))
    sin_corr = np.dot(window, np.sin(2 * np.pi * TONE_HZ * t))
    tone_energy = (cos_corr**2 + sin_corr**2) * 2.0 / (n**2)
    total_energy = float(np.mean(window**2)) + 1e-12
    return tone_energy / total_energy


def find_voice_start_sample(samples: np.ndarray, sample_rate_hz: float) -> int | None:
    """Sample index where the attention tone ends and voice begins, or
    `None` if no run of at least `MIN_TONE_SECONDS` of dominant 1050 Hz
    energy is found. Returning `None` rather than a best-effort guess
    matches the hallucination-guard posture in the module docstring: a
    wrong trim point is worse than no trim at all."""
    window_samples = max(1, int(WINDOW_SECONDS * sample_rate_hz))
    num_windows = len(samples) // window_samples
    if num_windows == 0:
        return None
    is_tone = [
        _tone_energy_fraction(samples[i * window_samples : (i + 1) * window_samples], sample_rate_hz)
        >= ENERGY_FRACTION_THRESHOLD
        for i in range(num_windows)
    ]
    min_tone_windows = max(1, int(MIN_TONE_SECONDS / WINDOW_SECONDS))

    best_end = None
    best_len = 0
    run_start = None
    for i, tone in enumerate(is_tone + [False]):  # sentinel to flush a trailing run
        if tone:
            if run_start is None:
                run_start = i
            continue
        if run_start is not None:
            run_len = i - run_start
            if run_len >= min_tone_windows and run_len > best_len:
                best_len = run_len
                best_end = i
            run_start = None
    if best_end is None:
        return None
    return best_end * window_samples
