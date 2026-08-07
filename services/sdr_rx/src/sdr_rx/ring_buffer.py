"""Per-channel tmpfs ring buffer (design doc §3, "Ring buffer").

`segment-capture` (milestone 4) reads pre-roll audio from here instead of
racing the live ZMQ stream, so the SAME header audio itself is captured with
lead-in before `segment-capture` even knows a message is starting. Stores raw
discriminator output -- real-valued, native bin rate (`BIN_RATE_HZ`),
unresampled -- rather than either ZMQ output rate, since this buffer exists
for capture fidelity, not for one particular consumer.

Backed by a memory-mapped file (meant to live on a tmpfs mount) so the write
side can be a different process than any future reader.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .resample import BIN_RATE_HZ

WINDOW_SECONDS = 30


class ChannelRingBuffer:
    """Fixed-length circular buffer of one channel's raw discriminator output."""

    def __init__(
        self,
        directory: Path,
        channel: str,
        sample_rate_hz: int = BIN_RATE_HZ,
        window_seconds: int = WINDOW_SECONDS,
    ):
        self.channel = channel
        self.sample_rate_hz = sample_rate_hz
        self.capacity = sample_rate_hz * window_seconds
        directory.mkdir(parents=True, exist_ok=True)
        self._data_path = directory / f"{channel}.raw"
        self._meta_path = directory / f"{channel}.meta.json"
        self._mmap = np.memmap(self._data_path, dtype=np.float32, mode="w+", shape=(self.capacity,))
        self._write_pos = 0
        self._total_written = 0
        self._write_meta()

    def _write_meta(self) -> None:
        self._meta_path.write_text(
            json.dumps(
                {
                    "channel": self.channel,
                    "sample_rate_hz": self.sample_rate_hz,
                    "capacity": self.capacity,
                    "write_pos": self._write_pos,
                    "total_written": self._total_written,
                }
            )
        )

    def write(self, samples: np.ndarray) -> None:
        samples = np.asarray(samples, dtype=np.float32)
        incoming = len(samples)
        if incoming == 0:
            return
        if incoming >= self.capacity:
            self._mmap[:] = samples[-self.capacity :]
            self._write_pos = 0
        else:
            end = self._write_pos + incoming
            if end <= self.capacity:
                self._mmap[self._write_pos : end] = samples
            else:
                first = self.capacity - self._write_pos
                self._mmap[self._write_pos :] = samples[:first]
                self._mmap[: incoming - first] = samples[first:]
            self._write_pos = end % self.capacity
        self._total_written += incoming
        self._mmap.flush()
        self._write_meta()

    def read_last(self, n: int) -> np.ndarray:
        """Most recent min(n, capacity, total written so far) samples, oldest first."""
        n = min(n, self.capacity, self._total_written)
        if n == 0:
            return np.zeros(0, dtype=np.float32)
        start = (self._write_pos - n) % self.capacity
        if start + n <= self.capacity:
            return np.array(self._mmap[start : start + n])
        first = self.capacity - start
        return np.concatenate([self._mmap[start:], self._mmap[: n - first]])

    def close(self) -> None:
        self._mmap.flush()
        del self._mmap
