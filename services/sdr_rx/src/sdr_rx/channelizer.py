"""48-bin odd-stacked, 2x-oversampled polyphase filterbank channelizer.

Channelizes the full 1.2 MS/s complex baseband stream into 48 bins of
50 kS/s complex each, with bin *centers* landing on LO + (k + 0.5) * 25 kHz
-- see channels.py for the frequency mapping. Seven of the 48 bins are the
NWR channels; the rest feed the spectrum/waterfall display.

## Algorithm

This is a polyphase filterbank realized via the standard "fold and FFT"
noble-identity trick, decomposed into two independent pieces:

1. **Odd stacking.** A real, even-stacked fold+FFT of an M-tap-per-branch
   prototype filter puts bin k at frequency k * Δf (DC-centered bin 0).
   To shift every bin center up by half a channel (Δf/2), the incoming
   *sample stream* is continuously multiplied by exp(-j*pi*n/M), where n is
   the sample's absolute index since the channelizer started -- NOT reset
   per output frame. This must run on the raw, continuous stream: applying
   the equivalent shift to the prototype filter instead (a tempting
   shortcut, since it looks like the same math per frame) silently breaks
   for every frequency exactly at an odd-stacked bin center, because it
   reintroduces a filter-envelope/alias cancellation that nulls the output
   -- caught by the swept-tone test in tests/test_channelizer.py.

2. **The 2x-oversampling artifact (hazard #1 from the design doc).**
   Decimation D = M/2 means the polyphase commutator advances only half a
   revolution between output frames, independent of odd/even stacking.
   Even-indexed bins land correctly every frame; odd-indexed bins pick up
   an extra 180-degree rotation on every other frame. Left uncorrected,
   this makes the odd bins' baseband output flip sign frame-to-frame --
   a channel that "works intermittently and drifts," per the design doc.
   The fix is a `(-1)^k` multiply applied to every bin on alternate
   ("odd") output frames only.

Implementation shape:

- Continuously demodulate the input by the half-bin ramp (step 1).
- Window each overlapping length-576 (= 48 * 12) segment with the real
  prototype filter.
- Fold (polyphase-sum) the 12 taps-per-bin down to 48 samples by aliasing.
- Batched 48-point FFT across all frames at once (hazard #2: never loop
  per frame calling fft() one at a time).
- Apply the `(-1)^k` correction (step 2) to alternate output frames.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import firwin

NUM_BINS = 48
TAPS_PER_BIN = 12
NUM_TAPS = NUM_BINS * TAPS_PER_BIN  # 576
DECIMATION = NUM_BINS // 2  # 24; 2x oversampled


def design_prototype_filter(num_bins: int = NUM_BINS, taps_per_bin: int = TAPS_PER_BIN) -> np.ndarray:
    """Real lowpass prototype: firwin, cutoff at 1/num_bins of Nyquist (one channel half-bandwidth)."""
    num_taps = num_bins * taps_per_bin
    cutoff = 1.0 / num_bins
    return firwin(num_taps, cutoff)


class PolyphaseChannelizer:
    """Streaming 48-bin odd-stacked polyphase channelizer.

    Feed it chunks of complex baseband samples via `process()`; it carries
    filter history, the half-bin modulator phase, and output-frame parity
    across calls, so chunk boundaries don't need to align to the
    decimation factor and results don't depend on how the stream is
    chunked.
    """

    def __init__(
        self,
        num_bins: int = NUM_BINS,
        taps_per_bin: int = TAPS_PER_BIN,
        decimation: int = DECIMATION,
        prototype: np.ndarray | None = None,
    ):
        self.num_bins = num_bins
        self.taps_per_bin = taps_per_bin
        self.decimation = decimation
        self.h = prototype if prototype is not None else design_prototype_filter(num_bins, taps_per_bin)
        self.num_taps = len(self.h)
        if self.num_taps != num_bins * taps_per_bin:
            raise ValueError("prototype filter length must equal num_bins * taps_per_bin")
        if self.num_taps % decimation != 0:
            raise ValueError("num_taps must be a multiple of decimation for history bookkeeping")

        self._odd_frame_correction = (-1.0) ** np.arange(num_bins)

        # Half-bin modulation period in samples: exp(-j*pi*n/M) repeats every 2M samples.
        self._mod_period = 2 * num_bins
        self._sample_index = 0  # position of the next unmodulated input sample, mod _mod_period

        self._history = np.zeros(self.num_taps - self.decimation, dtype=complex)  # already-modulated tail
        self._frame_parity = 0  # global output-frame counter mod 2

    def reset(self) -> None:
        self._sample_index = 0
        self._history = np.zeros(self.num_taps - self.decimation, dtype=complex)
        self._frame_parity = 0

    def _demodulate(self, samples: np.ndarray) -> np.ndarray:
        n = self._sample_index + np.arange(len(samples))
        ramp = np.exp(-1j * np.pi * (n % self._mod_period) / self.num_bins)
        self._sample_index = (self._sample_index + len(samples)) % self._mod_period
        return samples * ramp

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Consume `samples`, return an (n_frames, num_bins) complex array.

        n_frames depends on how many full decimation-length hops the
        combined history + new samples cover; it may be zero if too few
        samples have accumulated yet.
        """
        modulated = self._demodulate(np.asarray(samples, dtype=complex))
        x = np.concatenate([self._history, modulated])
        n_taps, d, m = self.num_taps, self.decimation, self.num_bins

        if len(x) < n_taps:
            self._history = x
            return np.zeros((0, m), dtype=complex)

        n_frames = (len(x) - n_taps) // d + 1

        frames = np.lib.stride_tricks.sliding_window_view(x, n_taps)[::d][:n_frames]

        windowed = frames * self.h[np.newaxis, :]
        folded = windowed.reshape(n_frames, self.taps_per_bin, m).sum(axis=1)

        spectrum = np.fft.fft(folded, axis=1)

        parities = (self._frame_parity + np.arange(n_frames)) % 2
        odd_rows = parities == 1
        if np.any(odd_rows):
            spectrum[odd_rows] *= self._odd_frame_correction[np.newaxis, :]

        self._frame_parity = (self._frame_parity + n_frames) % 2
        consumed = n_frames * d
        self._history = x[consumed:]
        return spectrum
