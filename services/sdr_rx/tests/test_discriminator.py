import numpy as np

from sdr_rx.discriminator import FMDiscriminator


def test_recovers_constant_frequency_deviation():
    fs = 50_000.0
    deviation_hz = 3_000.0
    n = 5_000
    t = np.arange(n) / fs
    x = np.exp(1j * 2 * np.pi * deviation_hz * t)

    disc = FMDiscriminator()
    freq_rad = disc.process(x)
    freq_hz = freq_rad * fs / (2 * np.pi)

    np.testing.assert_allclose(freq_hz[100:], deviation_hz, atol=1.0)


def test_zero_deviation_gives_zero_output():
    disc = FMDiscriminator()
    x = np.ones(1000, dtype=complex)
    out = disc.process(x)
    np.testing.assert_allclose(out, 0.0, atol=1e-12)


def test_first_call_returns_one_fewer_sample_subsequent_calls_match_input_length():
    disc = FMDiscriminator()
    first = disc.process(np.ones(100, dtype=complex))
    assert len(first) == 99
    second = disc.process(np.ones(50, dtype=complex))
    assert len(second) == 50


def test_chunking_matches_single_call():
    fs = 50_000.0
    t = np.arange(4000) / fs
    x = np.exp(1j * 2 * np.pi * 1500.0 * t)

    whole = FMDiscriminator().process(x)

    d = FMDiscriminator()
    parts = [d.process(x[i : i + 333]) for i in range(0, len(x), 333)]
    chunked = np.concatenate(parts)

    np.testing.assert_allclose(whole, chunked, atol=1e-10)


def test_precision_follows_the_input():
    fs = 50_000.0
    t = np.arange(4000) / fs
    x = np.exp(1j * 2 * np.pi * 1500.0 * t)

    assert FMDiscriminator().process(x.astype(np.complex64)).dtype == np.float32
    assert FMDiscriminator().process(x.astype(np.complex128)).dtype == np.float64


def test_float32_recovers_the_same_tone():
    """float32 resolves phase to ~1e-7 rad against a per-sample FM
    deviation measured in tenths of a radian, so narrowing must not move
    the recovered frequency in any way that matters."""
    fs = 50_000.0
    t = np.arange(4000) / fs
    x = np.exp(1j * 2 * np.pi * 1500.0 * t)

    wide = FMDiscriminator().process(x)
    narrow = FMDiscriminator().process(x.astype(np.complex64))
    np.testing.assert_allclose(narrow, wide, atol=1e-5)
