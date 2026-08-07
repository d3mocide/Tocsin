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


def test_separate_channels_use_separate_files(tmp_path):
    rb1 = ChannelRingBuffer(tmp_path, "WX1", sample_rate_hz=10, window_seconds=1)
    rb2 = ChannelRingBuffer(tmp_path, "WX2", sample_rate_hz=10, window_seconds=1)
    rb1.write(np.ones(5, dtype=np.float32))
    rb2.write(np.zeros(5, dtype=np.float32))
    np.testing.assert_allclose(rb1.read_last(5), np.ones(5))
    np.testing.assert_allclose(rb2.read_last(5), np.zeros(5))
