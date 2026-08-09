import numpy as np

from sdr_rx.dc_block import DCBlocker


def test_dc_input_decays_to_near_zero():
    blocker = DCBlocker()
    x = np.ones(20_000, dtype=complex)
    y = blocker.process(x)
    assert np.abs(y[-1]) < 1e-3
    assert np.abs(y[0]) > 0.5  # no delay-free discontinuity at the very first sample


def test_ac_tone_passes_with_near_unity_gain():
    """A tone well away from DC (e.g. the WX4/WX5 straddling artifact this
    blocker exists for) should pass through close to unaffected.
    """
    blocker = DCBlocker()
    fs = 1_200_000.0
    freq = 50_000.0
    n = 20_000
    t = np.arange(n) / fs
    tone = np.exp(1j * 2 * np.pi * freq * t)
    y = blocker.process(tone)
    steady = y[n // 2 :]
    assert np.abs(np.abs(steady) - 1.0).max() < 0.05


def test_state_carries_across_chunked_calls():
    blocker_whole = DCBlocker()
    blocker_chunked = DCBlocker()
    rng = np.random.default_rng(0)
    x = rng.normal(size=10_000) + 1j * rng.normal(size=10_000) + 0.5

    whole = blocker_whole.process(x)
    parts = [blocker_chunked.process(x[i : i + 333]) for i in range(0, len(x), 333)]
    chunked = np.concatenate(parts)

    np.testing.assert_allclose(whole, chunked, atol=1e-10)


def test_precision_follows_the_input():
    """complex64 in, complex64 out -- widening here would hand the
    channelizer a stream already doubled in size (dc_block.py's docstring)."""
    rng = np.random.default_rng(0)
    x = (rng.normal(size=1024) + 1j * rng.normal(size=1024)).astype(np.complex64)
    blocker = DCBlocker()
    assert blocker.process(x).dtype == np.complex64
    assert blocker.process(x.astype(np.complex128)).dtype == np.complex128


def test_narrow_precision_does_not_change_the_dc_response():
    """The float32 path has to block DC as well as the float64 one, not
    merely run faster. Compared against float64 on the same +0.5-offset
    input rather than against a fixed residual: this is a one-pole IIR with
    a ~2000-sample time constant, so the absolute residual at any given
    sample is a property of the filter, and what narrowing must not do is
    change it.
    """
    rng = np.random.default_rng(0)
    x = rng.normal(size=20_000) + 1j * rng.normal(size=20_000) + 0.5
    wide = DCBlocker().process(x)
    narrow = DCBlocker().process(x.astype(np.complex64))
    np.testing.assert_allclose(narrow, wide, atol=1e-5)
