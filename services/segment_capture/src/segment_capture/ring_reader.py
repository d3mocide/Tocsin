"""Read-only reader for `sdr_rx.ring_buffer.ChannelRingBuffer`'s on-disk
format (design doc §3, "Ring buffer"): a memory-mapped float32 circular
buffer of raw, unresampled discriminator output plus a JSON sidecar
(`write_pos`/`total_written`). Duplicates that small amount of file-format
knowledge rather than importing `sdr_rx` across the service boundary
(CLAUDE.md) -- the writer and reader are necessarily different processes
(`sdr_rx` owns the dongle; `segment_capture` doesn't) sharing a directory
mounted into both containers (`compose.yaml`'s `sdr-rx-ring` volume).

`sdr_rx`'s ring buffer only holds `WINDOW_SECONDS` (30s) of audio, but a
capture can legitimately run up to the 300s hard timeout (design doc §4) --
far longer than the buffer's capacity. So this reader is used two ways:
`start()` grabs whatever's already buffered (the SAME header itself, which
by the time `segment_capture`'s own multimon-ng decodes it and reports
`MessageStart` is already a few seconds in the past -- this is the
"pre-roll" the design doc calls for), and `read_new()` is then polled
repeatedly for the rest of the capture, faster than the 30s wraparound, so
no live audio is silently overwritten before it's been read.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

RING_BUFFER_SAMPLE_RATE_HZ = 50_000  # sdr_rx.resample.BIN_RATE_HZ


class RingBufferReader:
    def __init__(self, directory: Path, channel: str):
        self._data_path = directory / f"{channel}.raw"
        self._meta_path = directory / f"{channel}.meta.json"
        self._mmap: np.memmap | None = None
        self._mmap_capacity: int | None = None
        self._last_seen_total_written: int | None = None

    def _read_meta(self) -> dict:
        return json.loads(self._meta_path.read_text())

    def _mmap_for(self, capacity: int) -> np.memmap:
        if self._mmap is None or self._mmap_capacity != capacity:
            self._mmap = np.memmap(self._data_path, dtype=np.float32, mode="r", shape=(capacity,))
            self._mmap_capacity = capacity
        return self._mmap

    def _slice(self, meta: dict, n: int) -> np.ndarray:
        capacity = meta["capacity"]
        write_pos = meta["write_pos"]
        total_written = meta["total_written"]
        n = min(n, capacity, total_written)
        if n == 0:
            return np.zeros(0, dtype=np.float32)
        mmap = self._mmap_for(capacity)
        start = (write_pos - n) % capacity
        if start + n <= capacity:
            return np.array(mmap[start : start + n])
        first = capacity - start
        return np.concatenate([mmap[start:], mmap[: n - first]])

    def read_last(self, n: int) -> np.ndarray:
        """Most recent min(n, capacity, total written) samples, oldest first."""
        return self._slice(self._read_meta(), n)

    def start(self, preroll_samples: int) -> np.ndarray:
        """Call once when a capture begins: returns up to `preroll_samples`
        already-buffered audio, and resets the `read_new()` baseline to
        this same instant (one `meta.json` read for both, so the two can't
        race against one another)."""
        meta = self._read_meta()
        preroll = self._slice(meta, preroll_samples)
        self._last_seen_total_written = meta["total_written"]
        return preroll

    def read_new(self) -> tuple[np.ndarray, bool]:
        """New samples (oldest first) written since the last `start()` or
        `read_new()` call. The second element is `True` if more than a
        buffer's worth of audio arrived since then -- the gap is
        unrecoverable (already overwritten), and the caller should treat
        the capture as having a hole rather than silently splicing across
        it. Raises `RuntimeError` if called before `start()`."""
        if self._last_seen_total_written is None:
            raise RuntimeError("read_new() called before start()")
        meta = self._read_meta()
        delta = meta["total_written"] - self._last_seen_total_written
        self._last_seen_total_written = meta["total_written"]
        if delta <= 0:
            return np.zeros(0, dtype=np.float32), False
        overrun = delta > meta["capacity"]
        return self._slice(meta, meta["capacity"] if overrun else delta), overrun
