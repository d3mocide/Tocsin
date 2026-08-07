"""Quadrature FM discriminator for a single channelizer bin's output.

Instantaneous frequency (rad/sample) from the phase difference between
consecutive complex baseband samples -- the standard cheap NFM
discriminator, applied per-bin after the channelizer, before resampling
(design doc §3, "Output contract").
"""

from __future__ import annotations

import numpy as np


class FMDiscriminator:
    """Streaming discriminator; carries the last sample across calls so
    chunk boundaries don't drop a sample pair.

    The very first call across the lifetime of an instance returns one
    fewer sample than it was given, since there is no prior sample to
    difference the first one against. Every call after that returns
    exactly len(samples) outputs.
    """

    def __init__(self):
        self._prev: complex | None = None

    def reset(self) -> None:
        self._prev = None

    def process(self, samples: np.ndarray) -> np.ndarray:
        samples = np.asarray(samples, dtype=complex)
        if samples.size == 0:
            return np.zeros(0)
        joined = samples if self._prev is None else np.concatenate([[self._prev], samples])
        self._prev = samples[-1]
        return np.angle(joined[1:] * np.conj(joined[:-1]))
