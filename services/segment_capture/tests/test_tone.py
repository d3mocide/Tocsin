import numpy as np

from segment_capture.tone import find_voice_start_sample

SAMPLE_RATE = 50_000


def test_detects_tone_boundary_in_synthetic_signal():
    rng = np.random.default_rng(42)
    header_noise = rng.normal(0, 0.3, int(3 * SAMPLE_RATE)).astype(np.float32)
    t = np.arange(int(9 * SAMPLE_RATE)) / SAMPLE_RATE
    tone = np.sin(2 * np.pi * 1050.0 * t).astype(np.float32)
    voice_noise = rng.normal(0, 0.3, int(5 * SAMPLE_RATE)).astype(np.float32)
    samples = np.concatenate([header_noise, tone, voice_noise])

    boundary = find_voice_start_sample(samples, SAMPLE_RATE)

    assert boundary is not None
    expected = int(12 * SAMPLE_RATE)  # 3s header-ish noise + 9s tone
    assert abs(boundary - expected) <= 5000  # within one 0.1s window


def test_returns_none_when_no_tone_present():
    rng = np.random.default_rng(1)
    samples = rng.normal(0, 0.3, int(5 * SAMPLE_RATE)).astype(np.float32)
    assert find_voice_start_sample(samples, SAMPLE_RATE) is None


def test_returns_none_for_a_tone_blip_shorter_than_the_real_attention_tone():
    """A stray moment of energy near 1050 Hz (e.g. an AFSK symbol) must not
    be mistaken for the real 8-11s attention tone."""
    rng = np.random.default_rng(2)
    noise_a = rng.normal(0, 0.3, int(2 * SAMPLE_RATE)).astype(np.float32)
    t = np.arange(int(1 * SAMPLE_RATE)) / SAMPLE_RATE
    short_tone = np.sin(2 * np.pi * 1050.0 * t).astype(np.float32)
    noise_b = rng.normal(0, 0.3, int(2 * SAMPLE_RATE)).astype(np.float32)
    samples = np.concatenate([noise_a, short_tone, noise_b])
    assert find_voice_start_sample(samples, SAMPLE_RATE) is None


def test_returns_none_for_empty_input():
    assert find_voice_start_sample(np.zeros(0, dtype=np.float32), SAMPLE_RATE) is None
