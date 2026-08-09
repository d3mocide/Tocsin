import json

import numpy as np

from sdr_rx.ring_buffer import ChannelRingBuffer


def test_write_and_read_last_round_trip(tmp_path):
    rb = ChannelRingBuffer(tmp_path, "WX1", sample_rate_hz=100, window_seconds=1)
    assert rb.capacity == 100
    samples = np.arange(50, dtype=np.float32)
    rb.write(samples)
    out = rb.read_last(50)
    np.testing.assert_allclose(out, samples)


def test_wraps_around_when_single_write_exceeds_capacity(tmp_path):
    rb = ChannelRingBuffer(tmp_path, "WX1", sample_rate_hz=10, window_seconds=1)
    rb.write(np.arange(15, dtype=np.float32))
    out = rb.read_last(10)
    np.testing.assert_allclose(out, np.arange(5, 15, dtype=np.float32))


def test_multiple_writes_wrap_correctly(tmp_path):
    rb = ChannelRingBuffer(tmp_path, "WX1", sample_rate_hz=10, window_seconds=1)
    rb.write(np.arange(7, dtype=np.float32))
    rb.write(np.arange(7, 12, dtype=np.float32))
    out = rb.read_last(10)
    expected = np.concatenate([np.arange(7, dtype=np.float32), np.arange(7, 12, dtype=np.float32)])[-10:]
    np.testing.assert_allclose(out, expected)


def test_read_last_before_full_returns_available_only(tmp_path):
    rb = ChannelRingBuffer(tmp_path, "WX1", sample_rate_hz=100, window_seconds=1)
    rb.write(np.array([1.0, 2.0, 3.0], dtype=np.float32))
    out = rb.read_last(50)
    np.testing.assert_allclose(out, [1.0, 2.0, 3.0])


def test_empty_buffer_reads_nothing(tmp_path):
    rb = ChannelRingBuffer(tmp_path, "WX1", sample_rate_hz=100, window_seconds=1)
    assert rb.read_last(10).size == 0


def test_write_ignores_empty_input(tmp_path):
    rb = ChannelRingBuffer(tmp_path, "WX1", sample_rate_hz=100, window_seconds=1)
    rb.write(np.array([], dtype=np.float32))
    assert rb.read_last(10).size == 0


def test_metadata_file_reflects_total_written(tmp_path):
    rb = ChannelRingBuffer(tmp_path, "WX1", sample_rate_hz=10, window_seconds=1)
    rb.write(np.ones(3, dtype=np.float32))
    meta = json.loads((tmp_path / "WX1.meta.json").read_text())
    assert meta["total_written"] == 3
    assert meta["capacity"] == 10
    assert meta["channel"] == "WX1"


def test_writes_are_visible_to_a_separate_reader_mmap_without_flush(tmp_path):
    """Regression test for removing the per-write `.flush()` call (a real
    profiled hot spot -- see ring_buffer.py's comment): a second, independent
    `np.memmap` onto the same file -- standing in for `segment_capture`'s
    `RingBufferReader`, a genuinely separate process in production -- must
    still see writes immediately, since both are MAP_SHARED mappings of the
    same tmpfs-backed file and don't need msync for cross-mapping visibility."""
    rb = ChannelRingBuffer(tmp_path, "WX1", sample_rate_hz=10, window_seconds=1)
    reader_mmap = np.memmap(tmp_path / "WX1.raw", dtype=np.float32, mode="r", shape=(10,))

    rb.write(np.arange(1, 6, dtype=np.float32))
    np.testing.assert_allclose(np.array(reader_mmap[:5]), np.arange(1, 6, dtype=np.float32))

    rb.write(np.arange(6, 9, dtype=np.float32))
    np.testing.assert_allclose(np.array(reader_mmap[5:8]), np.arange(6, 9, dtype=np.float32))


def test_separate_channels_use_separate_files(tmp_path):
    rb1 = ChannelRingBuffer(tmp_path, "WX1", sample_rate_hz=10, window_seconds=1)
    rb2 = ChannelRingBuffer(tmp_path, "WX2", sample_rate_hz=10, window_seconds=1)
    rb1.write(np.ones(5, dtype=np.float32))
    rb2.write(np.zeros(5, dtype=np.float32))
    np.testing.assert_allclose(rb1.read_last(5), np.ones(5))
    np.testing.assert_allclose(rb2.read_last(5), np.zeros(5))
