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
    """y[n] = x[n] - x[n-1] + pole * y[n-1], carrying filter state across calls."""

    def __init__(self, pole: float = DEFAULT_POLE):
        self.pole = pole
        self._b = np.array([1.0, -1.0])
        self._a = np.array([1.0, -pole])
        self._zi = np.zeros(1, dtype=complex)

    def reset(self) -> None:
        self._zi = np.zeros(1, dtype=complex)

    def process(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=complex)
        y, self._zi = lfilter(self._b, self._a, x, zi=self._zi)
        return y
