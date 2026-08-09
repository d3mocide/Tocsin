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
- Window-and-fold each overlapping length-576 (= 48 * 12) segment against
  the real prototype filter, producing 48 samples per output frame (see
  "Blocked fold" below).
- Batched 48-point FFT across all frames at once (hazard #2: never loop
  per frame calling fft() one at a time).
- Apply the `(-1)^k` correction (step 2) to alternate output frames.

## Blocked fold

The fold is the whole cost of this stage, so how it's written matters more
than the FFT does. Writing it the obvious way -- materialize every frame's
576-tap window with `sliding_window_view`, multiply by the prototype, then
`.reshape(n_frames, 12, 48).sum(axis=1)` -- is correct but expands the
input by `num_taps / decimation` = 24x into a temporary before summing it
straight back down (25 MB per 65,536-sample chunk), and the stage becomes
memory-bandwidth bound on that temporary rather than compute bound on its
own arithmetic.

The multiply-accumulate can be reassociated to avoid the expansion
entirely. Writing the tap index as `f*D + t*M + m` and splitting the bin
index `m = q*D + m0` (with `R = M/D` = 2 sub-blocks per bin group):

    f*D + t*M + q*D + m0  ==  (f + t*R + q)*D + m0

-- i.e. every sample the fold touches lands at offset `m0` within some
length-`D` *block* of the input, so viewing the input as `(n_blocks, D)`
turns the whole fold into `R * taps_per_bin` shifted block-slices scaled
by one row of the prototype each and summed in place. Same arithmetic in
the same summation order (bit-identical output, not merely close), same
`h`, no 24x temporary, and each accumulation step is a `(n_frames, 24)`
slab that stays in cache.

## Sample precision

The working dtype follows the input: `complex64` in, `complex64`
throughout (RTL-SDR is an 8-bit ADC and `capture.py` already asks SoapySDR
for `CF32`, so float32 carries the samples with ~16 bits of headroom to
spare); anything else is promoted to `complex128`. Halving the width
halves the traffic through the bandwidth-bound fold above, which is most
of what this stage costs. `np.fft` would silently undo that -- it promotes
complex64 to complex128 -- so the FFT here is `scipy.fft`, which doesn't.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy.fft
from scipy.signal import firwin

NUM_BINS = 48
TAPS_PER_BIN = 12
NUM_TAPS = NUM_BINS * TAPS_PER_BIN  # 576
DECIMATION = NUM_BINS // 2  # 24; 2x oversampled


@dataclass
class _Workspace:
    """Everything `process()` needs at one working dtype, built once.

    `accumulator`/`scratch` are the blocked fold's running sums, reused
    across calls rather than reallocated per chunk: a steady capture hands
    over a constant chunk size, so after the first call these are already
    the right shape.
    """

    branch_taps: np.ndarray
    ramp_lut: np.ndarray
    accumulator: np.ndarray
    scratch: np.ndarray


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
        if num_bins % decimation != 0:
            raise ValueError("num_bins must be a multiple of decimation for the blocked fold")
        self._sub_blocks = num_bins // decimation  # R in the module docstring

        self._odd_frame_correction = (-1.0) ** np.arange(num_bins)

        # Half-bin modulation period in samples: exp(-j*pi*n/M) repeats every 2M samples.
        self._mod_period = 2 * num_bins
        self._sample_index = 0  # position of the next unmodulated input sample, mod _mod_period
        # The demodulation ramp only ever takes `_mod_period` distinct values
        # (it's periodic) -- precomputing them once and tiling it in
        # `_demodulate` avoids calling the transcendental `exp()` on every
        # sample of every chunk, which profiling showed was a real cost at
        # 1.2 MS/s (docs/design/tracking.md's 2026-08-09 entry). Same values,
        # just computed once instead of on every call.
        self._ramp_lut = np.exp(-1j * np.pi * np.arange(self._mod_period) / num_bins)

        # Working-dtype-dependent derivatives of `h`/`_ramp_lut`, plus the
        # fold's accumulators, all built on first use and reused after --
        # see `_workspace`.
        self._workspaces: dict[np.dtype, _Workspace] = {}

        self._history = np.zeros(self.num_taps - self.decimation, dtype=np.complex64)  # modulated tail
        self._frame_parity = 0  # global output-frame counter mod 2

    def reset(self) -> None:
        self._sample_index = 0
        self._history = np.zeros(self.num_taps - self.decimation, dtype=self._history.dtype)
        self._frame_parity = 0

    def _workspace(self, dtype: np.dtype) -> _Workspace:
        ws = self._workspaces.get(dtype)
        if ws is None:
            real = np.zeros(0, dtype=dtype).real.dtype
            ws = _Workspace(
                # (taps_per_bin, R, decimation): one prototype row per
                # (tap, sub-block), indexed exactly as the blocked fold
                # steps through it.
                branch_taps=self.h.astype(real).reshape(self.taps_per_bin, self._sub_blocks, self.decimation),
                ramp_lut=self._ramp_lut.astype(dtype),
                accumulator=np.zeros((0, self.decimation), dtype=dtype),
                scratch=np.zeros((0, self.decimation), dtype=dtype),
            )
            self._workspaces[dtype] = ws
        return ws

    def _demodulate(self, samples: np.ndarray, ramp_lut: np.ndarray) -> np.ndarray:
        n = len(samples)
        start = self._sample_index
        # `np.resize` tiles the LUT cyclically from index 0, so generate
        # `start + n` values and drop the first `start` (< _mod_period, so
        # the waste is bounded by 96 samples per call regardless of chunk
        # size). Cheaper than building the index array an arbitrary-offset
        # gather would need -- that costs an arange, an integer modulo, and
        # a fancy-index gather where this costs one tiled memcpy.
        ramp = np.resize(ramp_lut, start + n)[start:]
        self._sample_index = (start + n) % self._mod_period
        return samples * ramp

    def _fold(self, x: np.ndarray, n_frames: int, ws: _Workspace) -> np.ndarray:
        """Polyphase-fold `x` into `(n_frames, num_bins)`; see "Blocked fold"."""
        d, m, r = self.decimation, self.num_bins, self._sub_blocks
        blocks = x[: (len(x) // d) * d].reshape(-1, d)
        if ws.accumulator.shape[0] != n_frames:
            ws.accumulator = np.empty((n_frames, d), dtype=ws.accumulator.dtype)
            ws.scratch = np.empty((n_frames, d), dtype=ws.scratch.dtype)
        acc, scratch = ws.accumulator, ws.scratch

        folded = np.empty((n_frames, m), dtype=x.dtype)
        for q in range(r):
            np.multiply(blocks[q : q + n_frames], ws.branch_taps[0, q], out=acc)
            for t in range(1, self.taps_per_bin):
                offset = t * r + q
                np.multiply(blocks[offset : offset + n_frames], ws.branch_taps[t, q], out=scratch)
                acc += scratch
            folded[:, q * d : (q + 1) * d] = acc
        return folded

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Consume `samples`, return an (n_frames, num_bins) complex array.

        n_frames depends on how many full decimation-length hops the
        combined history + new samples cover; it may be zero if too few
        samples have accumulated yet.
        """
        samples = np.asarray(samples)
        dtype = samples.dtype if samples.dtype == np.complex64 else np.dtype(complex)
        ws = self._workspace(dtype)

        modulated = self._demodulate(samples.astype(dtype, copy=False), ws.ramp_lut)
        x = np.concatenate([self._history.astype(dtype, copy=False), modulated])
        n_taps, d, m = self.num_taps, self.decimation, self.num_bins

        if len(x) < n_taps:
            self._history = x
            return np.zeros((0, m), dtype=dtype)

        n_frames = (len(x) - n_taps) // d + 1

        spectrum = scipy.fft.fft(self._fold(x, n_frames, ws), axis=1, overwrite_x=True)

        # Rows needing the correction are those where (frame_parity + f) is
        # odd, i.e. every other row starting at `first_odd` -- a strided
        # slice, not the boolean mask this used to build, which paid for an
        # index array and a gather/scatter round trip to say the same thing.
        first_odd = 1 - self._frame_parity
        if first_odd < n_frames:
            spectrum[first_odd::2] *= self._odd_frame_correction

        self._frame_parity = (self._frame_parity + n_frames) % 2
        consumed = n_frames * d
        self._history = x[consumed:]
        return spectrum
