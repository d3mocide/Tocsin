import numpy as np
from scipy.signal import resample_poly

from sdr_rx.resample import BIN_RATE_HZ, MULTIMON_RATE_HZ, STT_RATE_HZ, to_multimon_rate, to_s16le, to_stt_rate


def _tone(freq_hz, n, fs=BIN_RATE_HZ):
    t = np.arange(n) / fs
    return np.sin(2 * np.pi * freq_hz * t)


def test_multimon_rate_ratio():
    audio = _tone(1000.0, BIN_RATE_HZ)  # 1 second at 50 kS/s
    out = to_multimon_rate(audio)
    assert abs(len(out) - MULTIMON_RATE_HZ) <= 1


def test_stt_rate_ratio():
    audio = _tone(1000.0, BIN_RATE_HZ)
    out = to_stt_rate(audio)
    assert abs(len(out) - STT_RATE_HZ) <= 1


def test_s16le_clips_and_converts_dtype():
    audio = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
    out = to_s16le(audio)
    assert out.dtype == np.int16
    np.testing.assert_array_equal(out, np.array([-32767, -32767, 0, 32767, 32767], dtype=np.int16))


def test_multimon_rate_matches_scipys_uncached_default_filter():
    """The cached-filter fast path (_resample_poly_filter) must not change
    output versus resample_poly's own default (redesigned-every-call)
    filter -- this is a pure performance change, not a DSP one."""
    audio = _tone(1000.0, BIN_RATE_HZ)
    np.testing.assert_allclose(to_multimon_rate(audio), resample_poly(audio, 441, 1000))


def test_stt_rate_matches_scipys_uncached_default_filter():
    audio = _tone(1000.0, BIN_RATE_HZ)
    np.testing.assert_allclose(to_stt_rate(audio), resample_poly(audio, 8, 25))
