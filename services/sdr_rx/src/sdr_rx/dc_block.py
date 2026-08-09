"""Single-pole DC blocker for the complex baseband stream.

The LO sits on a bin edge (see channels.py), so the RTL-SDR's DC spike
straddles WX4/WX5. This must run before channelization or it leaks into
both of those channels.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

DEFAULT_POLE = 0.9995


class DCBlocker:
    """y[n] = x[n] - x[n-1] + pole * y[n-1], carrying filter state across calls.

    Precision follows the input, as it does through the channelizer (see
    that module's "Sample precision"): complex64 samples stay complex64
    rather than being widened here and handed to the channelizer already
    doubled in size. `lfilter` picks its working type from the *widest* of
    signal, coefficients, and `zi`, so the coefficients have to be narrowed
    alongside the state -- float64 taps alone would silently promote the
    whole stream back to complex128.
    """

    def __init__(self, pole: float = DEFAULT_POLE):
        self.pole = pole
        self._b = np.array([1.0, -1.0])
        self._a = np.array([1.0, -pole])
        self._taps: dict[np.dtype, tuple[np.ndarray, np.ndarray]] = {}
        self._zi = np.zeros(1, dtype=np.complex64)

    def reset(self) -> None:
        self._zi = np.zeros(1, dtype=self._zi.dtype)

    def process(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x)
        dtype = x.dtype if x.dtype == np.complex64 else np.dtype(complex)
        taps = self._taps.get(dtype)
        if taps is None:
            real = np.zeros(0, dtype=dtype).real.dtype
            taps = (self._b.astype(real), self._a.astype(real))
            self._taps[dtype] = taps
        y, self._zi = lfilter(taps[0], taps[1], x.astype(dtype, copy=False), zi=self._zi.astype(dtype, copy=False))
        return y
