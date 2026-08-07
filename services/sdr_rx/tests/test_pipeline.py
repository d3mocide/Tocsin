import numpy as np
import pytest

from sdr_rx.channels import nwr_bins
from sdr_rx.pipeline import DevicePipeline
from sdr_rx.ring_buffer import ChannelRingBuffer

FS = 1_200_000.0


class FakePublisher:
    def __init__(self):
        self.calls = []

    def publish(self, topic, channel, sample_rate_hz, pcm):
        self.calls.append((topic, channel, sample_rate_hz, np.asarray(pcm)))


def _ring_buffers(tmp_path):
    return {b.channel: ChannelRingBuffer(tmp_path, b.channel, window_seconds=1) for b in nwr_bins()}


def test_process_publishes_both_streams_for_every_nwr_channel(tmp_path):
    publisher = FakePublisher()
    ring_buffers = _ring_buffers(tmp_path)
    pipeline = DevicePipeline("site-a", publisher, ring_buffers)

    n_samples = 200_000
    t = np.arange(n_samples) / FS
    tone = np.exp(1j * 2 * np.pi * 12_500.0 * t)  # WX5 (k=0) bin center
    pipeline.process(tone)

    channels_published = {call[1] for call in publisher.calls}
    assert channels_published == {b.channel for b in nwr_bins()}

    topics_published = {call[0] for call in publisher.calls}
    assert topics_published == {"same", "stt"}


def test_process_writes_tone_energy_into_the_target_channels_ring_buffer(tmp_path):
    publisher = FakePublisher()
    ring_buffers = _ring_buffers(tmp_path)
    pipeline = DevicePipeline("site-a", publisher, ring_buffers)

    n_samples = 200_000
    t = np.arange(n_samples) / FS
    tone = np.exp(1j * 2 * np.pi * 12_500.0 * t)  # WX5
    pipeline.process(tone)

    wx5 = ring_buffers["WX5"].read_last(10_000)
    assert wx5.size > 0

    wx1 = ring_buffers["WX1"].read_last(10_000)
    assert wx1.size > 0


def test_process_is_a_no_op_below_the_channelizer_history_length():
    publisher = FakePublisher()
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        ring_buffers = _ring_buffers(Path(d))
        pipeline = DevicePipeline("site-a", publisher, ring_buffers)
        pipeline.process(np.ones(10, dtype=complex))
        assert publisher.calls == []


def test_missing_ring_buffer_for_an_nwr_channel_raises(tmp_path):
    publisher = FakePublisher()
    ring_buffers = _ring_buffers(tmp_path)
    del ring_buffers["WX5"]
    with pytest.raises(ValueError, match="WX5"):
        DevicePipeline("site-a", publisher, ring_buffers)


def test_run_forever_stops_on_predicate(tmp_path):
    publisher = FakePublisher()
    ring_buffers = _ring_buffers(tmp_path)
    pipeline = DevicePipeline("site-a", publisher, ring_buffers)

    calls = {"n": 0}

    class CountingSource:
        def read_chunk(self):
            calls["n"] += 1
            return np.zeros(0, dtype=complex)

    pipeline.run_forever(CountingSource(), stop=lambda: calls["n"] >= 3)
    assert calls["n"] == 3
