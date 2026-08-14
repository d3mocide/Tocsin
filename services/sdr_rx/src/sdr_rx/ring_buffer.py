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
import os
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
        """Written atomically (temp file + `os.replace`), never in place.

        `Path.write_text` truncates to zero bytes before rewriting, and this
        runs on *every* `write()` -- i.e. continuously, per channel, at audio
        chunk rate. Any reader that opens the file inside that window gets an
        empty string and dies on `json.loads`. `segment_capture`'s alert
        capture only reads the ring buffer during an actual SAME message, so
        it hit that window rarely enough to never surface; the live segmenter
        reads it on every tick and hit it constantly
        (`JSONDecodeError: Expecting value: line 1 column 1 (char 0)` --
        docs/design/tracking.md, 2026-08-14). `os.replace` is atomic on POSIX,
        so a reader now always sees either the previous meta or the new one,
        never a torn one. The temp file is per-channel, so concurrent writers
        for different channels can't clobber each other's rename.
        """
        payload = json.dumps(
            {
                "channel": self.channel,
                "sample_rate_hz": self.sample_rate_hz,
                "capacity": self.capacity,
                "write_pos": self._write_pos,
                "total_written": self._total_written,
            }
        )
        tmp_path = self._meta_path.with_name(f"{self._meta_path.name}.tmp")
        tmp_path.write_text(payload)
        os.replace(tmp_path, self._meta_path)

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
        # No `.flush()` here: this only lives on tmpfs (module docstring),
        # and the reader (segment_capture's RingBufferReader) opens its own
        # MAP_SHARED mmap of the same file -- both mappings share the same
        # page-cache pages, so writes are visible to the reader immediately
        # without an msync. `flush()`/msync exists to persist dirty pages to
        # a *backing store*, which tmpfs doesn't have; profiled on a live
        # pipeline, it cost ~0.4ms per call, called once per channel per
        # chunk (docs/design/tracking.md's 2026-08-09 entry) for no
        # cross-process-visibility benefit. Still called once in `close()`
        # for a clean shutdown.
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
