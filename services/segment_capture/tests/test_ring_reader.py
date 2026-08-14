import json
from pathlib import Path

import numpy as np
import pytest

from segment_capture.ring_reader import RingBufferReader


class _FakeRingBufferWriter:
    """Mimics `sdr_rx.ring_buffer.ChannelRingBuffer`'s on-disk format
    closely enough to test `RingBufferReader` against it, without
    importing `sdr_rx` (service boundary, CLAUDE.md)."""

    def __init__(self, directory: Path, channel: str, capacity: int):
        directory.mkdir(parents=True, exist_ok=True)
        self._data_path = directory / f"{channel}.raw"
        self._meta_path = directory / f"{channel}.meta.json"
        self._channel = channel
        self._capacity = capacity
        self._mmap = np.memmap(self._data_path, dtype=np.float32, mode="w+", shape=(capacity,))
        self._write_pos = 0
        self._total_written = 0
        self._write_meta()

    def _write_meta(self) -> None:
        self._meta_path.write_text(
            json.dumps(
                {
                    "channel": self._channel,
                    "sample_rate_hz": 50_000,
                    "capacity": self._capacity,
                    "write_pos": self._write_pos,
                    "total_written": self._total_written,
                }
            )
        )

    def write(self, samples: np.ndarray) -> None:
        incoming = len(samples)
        if incoming >= self._capacity:
            self._mmap[:] = samples[-self._capacity :]
            self._write_pos = 0
        else:
            end = self._write_pos + incoming
            if end <= self._capacity:
                self._mmap[self._write_pos : end] = samples
            else:
                first = self._capacity - self._write_pos
                self._mmap[self._write_pos :] = samples[:first]
                self._mmap[: incoming - first] = samples[first:]
            self._write_pos = end % self._capacity
        self._total_written += incoming
        self._mmap.flush()
        self._write_meta()


def test_read_last_returns_most_recent_samples_oldest_first(tmp_path):
    writer = _FakeRingBufferWriter(tmp_path, "WX5", capacity=10)
    writer.write(np.arange(10, dtype=np.float32))
    reader = RingBufferReader(tmp_path, "WX5")
    assert list(reader.read_last(5)) == [5, 6, 7, 8, 9]


def test_read_last_caps_at_total_written(tmp_path):
    writer = _FakeRingBufferWriter(tmp_path, "WX5", capacity=10)
    writer.write(np.array([1, 2, 3], dtype=np.float32))
    reader = RingBufferReader(tmp_path, "WX5")
    assert list(reader.read_last(10)) == [1, 2, 3]


def test_read_last_handles_wraparound(tmp_path):
    writer = _FakeRingBufferWriter(tmp_path, "WX5", capacity=5)
    writer.write(np.array([1, 2, 3, 4, 5], dtype=np.float32))
    writer.write(np.array([6, 7], dtype=np.float32))
    reader = RingBufferReader(tmp_path, "WX5")
    assert list(reader.read_last(5)) == [3, 4, 5, 6, 7]


def test_start_returns_preroll(tmp_path):
    writer = _FakeRingBufferWriter(tmp_path, "WX5", capacity=10)
    writer.write(np.arange(10, dtype=np.float32))
    reader = RingBufferReader(tmp_path, "WX5")
    assert list(reader.start(4)) == [6, 7, 8, 9]


def test_read_new_returns_samples_written_after_start(tmp_path):
    writer = _FakeRingBufferWriter(tmp_path, "WX5", capacity=10)
    writer.write(np.arange(5, dtype=np.float32))
    reader = RingBufferReader(tmp_path, "WX5")
    reader.start(3)
    writer.write(np.array([100, 101], dtype=np.float32))
    new_samples, overrun = reader.read_new()
    assert list(new_samples) == [100, 101]
    assert overrun is False


def test_read_new_reports_overrun_past_capacity(tmp_path):
    writer = _FakeRingBufferWriter(tmp_path, "WX5", capacity=5)
    writer.write(np.arange(5, dtype=np.float32))
    reader = RingBufferReader(tmp_path, "WX5")
    reader.start(5)
    writer.write(np.arange(100, 107, dtype=np.float32))  # 7 new samples > capacity 5
    new_samples, overrun = reader.read_new()
    assert overrun is True
    assert len(new_samples) == 5


def test_read_new_before_start_raises(tmp_path):
    writer = _FakeRingBufferWriter(tmp_path, "WX5", capacity=5)
    writer.write(np.arange(5, dtype=np.float32))
    reader = RingBufferReader(tmp_path, "WX5")
    with pytest.raises(RuntimeError):
        reader.read_new()


def test_read_new_returns_nothing_when_no_new_samples(tmp_path):
    writer = _FakeRingBufferWriter(tmp_path, "WX5", capacity=5)
    writer.write(np.arange(5, dtype=np.float32))
    reader = RingBufferReader(tmp_path, "WX5")
    reader.start(5)
    new_samples, overrun = reader.read_new()
    assert len(new_samples) == 0
    assert overrun is False


def test_meta_read_retries_a_torn_sidecar_then_succeeds(tmp_path, monkeypatch):
    """Defense in depth for a mid-upgrade mismatch: an *older* sdr-rx still
    writes the sidecar in place (truncate-then-write), leaving a zero-byte
    window. A capture in progress must not die on that."""
    writer = _FakeRingBufferWriter(tmp_path, "WX5", capacity=10)
    writer.write(np.arange(5, dtype=np.float32))
    reader = RingBufferReader(tmp_path, "WX5")

    meta_path = tmp_path / "WX5.meta.json"
    real_text = meta_path.read_text()
    reads = iter(["", "", real_text])
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: next(reads))

    assert reader._read_meta()["total_written"] == 5


def test_meta_read_gives_up_after_repeated_torn_reads(tmp_path, monkeypatch):
    writer = _FakeRingBufferWriter(tmp_path, "WX5", capacity=10)
    writer.write(np.arange(5, dtype=np.float32))
    reader = RingBufferReader(tmp_path, "WX5")

    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: "")
    with pytest.raises(json.JSONDecodeError):
        reader._read_meta()


def test_missing_meta_file_still_raises_immediately(tmp_path):
    """A missing file means the ring buffer doesn't exist -- a startup or
    configuration condition the caller must see, not a transient torn read
    worth retrying."""
    reader = RingBufferReader(tmp_path, "NOPE")
    with pytest.raises(FileNotFoundError):
        reader._read_meta()
