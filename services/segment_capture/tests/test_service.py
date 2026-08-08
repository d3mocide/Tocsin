import sys
import time

import numpy as np

from segment_capture.service import SegmentCaptureService


class FakePublisher:
    def __init__(self):
        self.results = []

    def publish(self, result):
        self.results.append(result)


class FakeRingReader:
    """Stands in for a real ring buffer directory -- these tests exercise
    the boundary-detection/finalize wiring, not the ring-buffer file
    format itself (see test_ring_reader.py for that)."""

    def __init__(self, directory, channel):
        self.directory = directory
        self.channel = channel

    def start(self, preroll_samples):
        return np.zeros(10, dtype=np.float32)

    def read_new(self):
        return np.zeros(0, dtype=np.float32), False


def _fake_multimon_command(*output_lines: str) -> list[str]:
    lines_repr = repr(list(output_lines))
    script = (
        "import sys\n"
        "sys.stdin.buffer.read(4)\n"
        f"for line in {lines_repr}:\n"
        "    print(line, flush=True)\n"
        "sys.stdin.buffer.read()\n"
    )
    return [sys.executable, "-c", script]


def _feed_until(service, feeds, condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not condition():
        for site, channel in feeds:
            service.feed(site, channel, b"\x00\x00\x00\x00")
        time.sleep(0.02)


def test_zczc_then_eom_triggers_a_finalized_capture(tmp_path):
    publisher = FakePublisher()
    service = SegmentCaptureService(
        ring_buffer_dir=tmp_path,
        output_dir=tmp_path / "captures",
        publisher=publisher,
        multimon_command=_fake_multimon_command("EAS: ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-", "EAS: NNNN"),
        ring_reader_factory=FakeRingReader,
    )

    _feed_until(service, [("home", "WX5")], lambda: len(publisher.results) >= 1)

    assert len(publisher.results) == 1
    result = publisher.results[0]
    assert result.site == "home"
    assert result.channel == "WX5"
    assert result.event_code == "TOR"
    assert result.wav_path.exists()

    service.close()


def test_eom_without_active_capture_is_ignored(tmp_path):
    publisher = FakePublisher()
    service = SegmentCaptureService(
        ring_buffer_dir=tmp_path,
        output_dir=tmp_path / "captures",
        publisher=publisher,
        multimon_command=_fake_multimon_command("EAS: NNNN"),
        ring_reader_factory=FakeRingReader,
    )
    for _ in range(10):
        service.feed("home", "WX5", b"\x00\x00\x00\x00")
        time.sleep(0.02)
    assert publisher.results == []
    service.close()


def test_tick_finalizes_a_capture_that_times_out(tmp_path):
    publisher = FakePublisher()
    service = SegmentCaptureService(
        ring_buffer_dir=tmp_path,
        output_dir=tmp_path / "captures",
        publisher=publisher,
        multimon_command=_fake_multimon_command("EAS: ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-"),
        ring_reader_factory=FakeRingReader,
        hard_timeout_seconds=0.05,
    )
    _feed_until(service, [("home", "WX5")], lambda: len(service._recorders) == 1)
    time.sleep(0.1)
    service.tick()

    assert len(publisher.results) == 1
    assert publisher.results[0].timed_out is True
    service.close()


def test_different_channels_get_independent_captures(tmp_path):
    publisher = FakePublisher()
    service = SegmentCaptureService(
        ring_buffer_dir=tmp_path,
        output_dir=tmp_path / "captures",
        publisher=publisher,
        multimon_command=_fake_multimon_command("EAS: ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-", "EAS: NNNN"),
        ring_reader_factory=FakeRingReader,
    )
    _feed_until(service, [("home", "WX5"), ("home", "WX1")], lambda: len(publisher.results) >= 2)
    assert {(r.site, r.channel) for r in publisher.results} == {("home", "WX5"), ("home", "WX1")}
    service.close()
