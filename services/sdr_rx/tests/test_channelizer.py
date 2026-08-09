import numpy as np
import pytest

from sdr_rx.channelizer import (
    NUM_BINS,
    NUM_TAPS,
    PolyphaseChannelizer,
    design_prototype_filter,
)
from sdr_rx.channels import LO_HZ, bin_frequency_hz, nwr_bins

FS = 1_200_000.0

# All seven NWR channels, plus a spread of spectrum-only bins (positive,
# negative, and near the edges of the 48-bin range).
SWEEP_KS = [-4, -3, -2, -1, 0, 1, 2, 5, -10, 23, -24]


# The pipeline runs in complex64 end to end -- SoapySDR hands over CF32
# (capture.py) and nothing widens it (channelizer.py's "Sample precision").
# Every hazard assertion below is parametrized over both precisions at the
# *same* tolerance rather than granting float32 a looser one: an 8-bit ADC's
# samples do not need float64 to channelize correctly, and if the float32
# path could not hold this bar it would not be the right default.
DTYPES = [np.complex128, np.complex64]


def _run_tone(
    freq_hz: float, n_samples: int = 200_000, chunk: int | None = None, dtype=np.complex128
) -> np.ndarray:
    ch = PolyphaseChannelizer()
    t = np.arange(n_samples) / FS
    tone = np.exp(1j * 2 * np.pi * freq_hz * t).astype(dtype)
    if chunk is None:
        return ch.process(tone)
    parts = [ch.process(tone[i : i + chunk]) for i in range(0, n_samples, chunk)]
    return np.concatenate(parts, axis=0)


@pytest.mark.parametrize("dtype", DTYPES)
def test_process_preserves_input_precision(dtype):
    out = _run_tone(12_500.0, n_samples=48_000, dtype=dtype)
    assert out.dtype == dtype


@pytest.mark.parametrize("k", SWEEP_KS)
def test_swept_tone_constant_amplitude_at_bin_center(k):
    """Regression test for design-doc hazard #1: a tone parked exactly on
    an odd-stacked bin center must show constant amplitude in that bin,
    frame after frame, once the startup transient decays. An earlier
    implementation attempt (using the algebraically tempting shortcut of
    folding the half-bin shift into the prototype filter instead of
    demodulating the raw stream) nulled this to exactly zero once the
    filter's startup transient decayed -- a channel that "works
    intermittently" is exactly the failure mode this guards against.
    """
    for dtype in DTYPES:
        freq = (k + 0.5) * 25_000.0
        out = _run_tone(freq, dtype=dtype)
        steady = out[len(out) // 2 :]  # drop startup transient
        mag = np.abs(steady[:, k % NUM_BINS])
        assert mag.mean() > 0.9
        assert mag.std() < 1e-6
        assert mag.min() > mag.mean() - 1e-6


@pytest.mark.parametrize("k", [-4, -1, 0, 2, 23])
@pytest.mark.parametrize("dtype", DTYPES)
def test_result_independent_of_chunk_boundaries(k, dtype):
    """Streaming callers won't hand samples in decimation-aligned chunks;
    verify chunking doesn't change the result (history/parity bookkeeping
    across process() calls must be exact, not just approximately right).
    """
    freq = (k + 0.5) * 25_000.0
    whole = _run_tone(freq, n_samples=48_000, dtype=dtype)
    chunked = _run_tone(freq, n_samples=48_000, chunk=777, dtype=dtype)
    n = min(len(whole), len(chunked))
    assert n > 0
    np.testing.assert_allclose(whole[:n], chunked[:n], atol=1e-8)


@pytest.mark.parametrize("dtype", DTYPES)
def test_single_tone_does_not_leak_into_distant_bins(dtype):
    k = 0
    freq = (k + 0.5) * 25_000.0
    out = _run_tone(freq, dtype=dtype)
    steady = out[len(out) // 2 :]
    energy = np.abs(steady).mean(axis=0)
    assert energy[k % NUM_BINS] > 0.9
    far_bin = (k + 20) % NUM_BINS
    assert energy[far_bin] < 1e-3


@pytest.mark.parametrize("dtype", DTYPES)
def test_blocked_fold_matches_the_direct_windowed_formulation(dtype):
    """The fold is reassociated for speed (channelizer.py's "Blocked
    fold"); it must stay the *same* arithmetic in the same order, not an
    approximation of it. Checks it against the textbook
    sliding-window/multiply/reshape-sum form the docstring derives it from,
    demanding bit-equality rather than a tolerance -- a reassociation that
    only agreed to within rounding would mean the summation order had
    drifted, which is exactly the kind of silent change this guards.
    """
    ch = PolyphaseChannelizer()
    rng = np.random.default_rng(0)
    x = (rng.normal(size=8192) + 1j * rng.normal(size=8192)).astype(dtype)
    n_frames = (len(x) - NUM_TAPS) // ch.decimation + 1
    ws = ch._workspace(np.dtype(dtype))

    frames = np.lib.stride_tricks.sliding_window_view(x, NUM_TAPS)[:: ch.decimation][:n_frames]
    expected = (frames * ws.branch_taps.reshape(-1)).reshape(n_frames, ch.taps_per_bin, NUM_BINS).sum(axis=1)

    np.testing.assert_array_equal(ch._fold(x, n_frames, ws), expected)


def test_rejects_decimation_that_does_not_divide_num_bins():
    """The blocked fold splits each bin index into whole sub-blocks of
    `decimation` samples, which only exists if the two divide."""
    with pytest.raises(ValueError, match="num_bins must be a multiple of decimation"):
        # 32 divides num_taps (576), so this clears the history-bookkeeping
        # check above it and reaches the one under test.
        PolyphaseChannelizer(num_bins=48, taps_per_bin=12, decimation=32, prototype=np.ones(576))


def test_odd_frame_correction_is_required_for_phase_stability():
    """Direct regression test for the (-1)^k hazard itself.

    Because D = num_bins / 2 (2x oversampling), odd-indexed bins pick up a
    spurious 180-degree rotation every other output frame unless
    corrected. That does NOT show up as an amplitude change -- a sign
    flip doesn't change magnitude -- so the amplitude tests above cannot
    catch it on their own; this test checks frame-to-frame phase
    stability directly. Uncorrected, this flip aliases straight into the
    audio band once the channel feeds an FM discriminator (phase
    difference between consecutive decimated samples), which is what
    "drifts" means in the design doc.
    """
    k = 1  # odd bin index
    freq = (k + 0.5) * 25_000.0
    n_samples = 48_000
    t = np.arange(n_samples) / FS

    for dtype in DTYPES:
        tone = np.exp(1j * 2 * np.pi * freq * t).astype(dtype)

        ch = PolyphaseChannelizer()
        out = ch.process(tone)
        steady = out[len(out) // 2 :, k % NUM_BINS]
        phase_diff = np.angle(steady[1:] * np.conj(steady[:-1]))
        assert np.abs(phase_diff).max() < 1e-6  # corrected: stable phase, no per-frame flips

        ch_broken = PolyphaseChannelizer()
        ch_broken._odd_frame_correction = np.ones(NUM_BINS)  # simulate omitting the fix
        out_broken = ch_broken.process(tone)
        steady_broken = out_broken[len(out_broken) // 2 :, k % NUM_BINS]
        phase_diff_broken = np.angle(steady_broken[1:] * np.conj(steady_broken[:-1]))
        assert np.abs(phase_diff_broken).max() > 3.0  # ~180 degree flips every other frame


def test_all_seven_nwr_channels_map_to_expected_bins():
    names = {b.channel: b.k for b in nwr_bins()}
    assert names == {
        "WX1": -4,
        "WX2": -3,
        "WX3": -2,
        "WX4": -1,
        "WX5": 0,
        "WX6": 1,
        "WX7": 2,
    }
    assert bin_frequency_hz(0) == LO_HZ + 12_500.0


def test_prototype_filter_shape():
    h = design_prototype_filter()
    assert h.shape == (NUM_TAPS,)
    assert np.isrealobj(h)


def test_rejects_mismatched_prototype_length():
    with pytest.raises(ValueError):
        PolyphaseChannelizer(prototype=np.ones(10))
