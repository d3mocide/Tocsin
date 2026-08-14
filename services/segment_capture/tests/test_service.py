import sys
import time

import numpy as np

from segment_capture.service import SegmentCaptureService
from segment_capture.tiers import TierTable


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


def test_tier_is_looked_up_from_the_injected_tier_table(tmp_path):
    publisher = FakePublisher()
    tiers = TierTable({"TOR": {"name": "Tornado Warning", "tier": "A"}})
    service = SegmentCaptureService(
        ring_buffer_dir=tmp_path,
        output_dir=tmp_path / "captures",
        publisher=publisher,
        tiers=tiers,
        multimon_command=_fake_multimon_command("EAS: ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-", "EAS: NNNN"),
        ring_reader_factory=FakeRingReader,
    )
    _feed_until(service, [("home", "WX5")], lambda: len(publisher.results) >= 1)
    assert publisher.results[0].tier == "A"
    assert publisher.results[0].raw_header == "ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-"
    service.close()


def test_unrecognized_event_code_falls_back_to_tier_b(tmp_path):
    publisher = FakePublisher()
    service = SegmentCaptureService(
        ring_buffer_dir=tmp_path,
        output_dir=tmp_path / "captures",
        publisher=publisher,
        tiers=TierTable({}),
        multimon_command=_fake_multimon_command("EAS: ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-", "EAS: NNNN"),
        ring_reader_factory=FakeRingReader,
    )
    _feed_until(service, [("home", "WX5")], lambda: len(publisher.results) >= 1)
    assert publisher.results[0].tier == "B"
    service.close()


class _FakeLiveSegmenter:
    """Stands in for `live_segmenter.LiveSegmenter` -- these tests exercise
    `SegmentCaptureService`'s wiring (lazy construction, one poll per
    `tick()`, publishing whatever comes back), not the VAD/cut logic
    itself (that's test_live_segmenter.py's job)."""

    instances = []

    def __init__(self, site, channel, ring_reader, output_dir):
        self.site = site
        self.channel = channel
        self.ring_reader = ring_reader
        self.output_dir = output_dir
        self.poll_calls = 0
        type(self).instances.append(self)

    def poll(self):
        self.poll_calls += 1
        return [f"result-from-{self.site}-{self.channel}-{self.poll_calls}"]


def test_tick_polls_the_configured_live_channel(tmp_path):
    _FakeLiveSegmenter.instances = []
    publisher = FakePublisher()
    publisher.live_results = []
    publisher.publish_live = lambda result: publisher.live_results.append(result)
    service = SegmentCaptureService(
        ring_buffer_dir=tmp_path,
        output_dir=tmp_path / "captures",
        publisher=publisher,
        live_channel=("home", "WX7"),
        live_segmenter_factory=_FakeLiveSegmenter,
        ring_reader_factory=FakeRingReader,
    )
    service.tick()
    service.tick()

    assert len(_FakeLiveSegmenter.instances) == 1  # constructed once, lazily, not per tick()
    live_segmenter = _FakeLiveSegmenter.instances[0]
    assert live_segmenter.site == "home"
    assert live_segmenter.channel == "WX7"
    assert live_segmenter.poll_calls == 2
    assert publisher.live_results == ["result-from-home-WX7-1", "result-from-home-WX7-2"]
    service.close()


def test_tick_without_live_channel_never_touches_live_segmenter(tmp_path):
    _FakeLiveSegmenter.instances = []
    publisher = FakePublisher()
    service = SegmentCaptureService(
        ring_buffer_dir=tmp_path,
        output_dir=tmp_path / "captures",
        publisher=publisher,
        live_segmenter_factory=_FakeLiveSegmenter,
        ring_reader_factory=FakeRingReader,
    )
    service.tick()
    assert _FakeLiveSegmenter.instances == []
    service.close()


class _FakeLiveSegmenterThatFailsThenRecovers:
    """Reproduces the real bug: the ring buffer for the configured (site,
    channel) isn't readable yet (sdr-rx hasn't created it -- a startup
    race -- or LIVE_TRANSCRIPTION_SITE/_CHANNEL is misconfigured), which
    is exactly what `RingBufferReader.start()` raises `FileNotFoundError`
    for against a real ring buffer directory."""

    instances = []

    def __init__(self, site, channel, ring_reader, output_dir):
        self.site = site
        self.channel = channel
        self.poll_calls = 0
        type(self).instances.append(self)

    def poll(self):
        self.poll_calls += 1
        if self.poll_calls <= 2:
            raise FileNotFoundError(f"[Errno 2] No such file or directory: '{self.channel}.meta.json'")
        return [f"result-{self.poll_calls}"]


def test_tick_survives_a_live_segmenter_poll_failure_and_keeps_retrying(tmp_path, capsys):
    _FakeLiveSegmenterThatFailsThenRecovers.instances = []
    publisher = FakePublisher()
    publisher.live_results = []
    publisher.publish_live = lambda result: publisher.live_results.append(result)
    service = SegmentCaptureService(
        ring_buffer_dir=tmp_path,
        output_dir=tmp_path / "captures",
        publisher=publisher,
        live_channel=("home", "WX7"),
        live_segmenter_factory=_FakeLiveSegmenterThatFailsThenRecovers,
        ring_reader_factory=FakeRingReader,
    )

    # Two ticks fail (the "not created yet" race) -- must not raise, and
    # must not take the rest of the service down.
    service.tick()
    service.tick()
    assert publisher.live_results == []

    # A third tick, once the ring buffer exists, succeeds normally.
    service.tick()
    assert publisher.live_results == ["result-3"]

    err = capsys.readouterr().err
    assert err.count("segment-capture: live transcription can't read the ring buffer") == 1  # warned once, not per tick
    assert "LIVE_TRANSCRIPTION_SITE" in err
    service.close()


def test_live_failure_message_names_the_sites_that_do_exist(tmp_path):
    """The real deployment's message said only "can't read the ring buffer
    for PDX:49435794/WX7", which still left the operator guessing. Naming
    what sdr-rx actually created makes the mismatch obvious on sight."""

    class _AlwaysFails:
        def __init__(self, site, channel, ring_reader, output_dir):
            pass

        def poll(self):
            raise FileNotFoundError("[Errno 2] No such file or directory")

    (tmp_path / "PDX").mkdir()
    (tmp_path / "PDX" / "WX7.meta.json").write_text("{}")
    (tmp_path / "PDX" / "WX1.meta.json").write_text("{}")

    service = SegmentCaptureService(
        ring_buffer_dir=tmp_path,
        output_dir=tmp_path / "captures",
        publisher=FakePublisher(),
        live_channel=("PDX:49435794", "WX7"),  # the exact bad value from the report
        live_segmenter_factory=_AlwaysFails,
        ring_reader_factory=FakeRingReader,
    )
    service.tick()
    message = service._describe_ring_buffers()
    assert "PDX (WX1, WX7)" == message
    service.close()


def test_ring_buffer_description_survives_a_missing_directory(tmp_path):
    service = SegmentCaptureService(
        ring_buffer_dir=tmp_path / "does-not-exist",
        output_dir=tmp_path / "captures",
        publisher=FakePublisher(),
        ring_reader_factory=FakeRingReader,
    )
    # Must not raise -- this only ever runs while reporting another failure.
    assert "unreadable" in service._describe_ring_buffers()
    service.close()


def test_ring_buffer_description_when_sdr_rx_has_not_started(tmp_path):
    service = SegmentCaptureService(
        ring_buffer_dir=tmp_path,
        output_dir=tmp_path / "captures",
        publisher=FakePublisher(),
        ring_reader_factory=FakeRingReader,
    )
    assert "no sites yet" in service._describe_ring_buffers()
    service.close()


def _service_with_failing_live_poll(tmp_path, exc):
    class _Fails:
        def __init__(self, site, channel, ring_reader, output_dir):
            pass

        def poll(self):
            raise exc

    return SegmentCaptureService(
        ring_buffer_dir=tmp_path,
        output_dir=tmp_path / "captures",
        publisher=FakePublisher(),
        live_channel=("PDX", "WX7"),
        live_segmenter_factory=_Fails,
        ring_reader_factory=FakeRingReader,
    )


def test_missing_ring_buffer_message_points_at_the_config(tmp_path, capsys):
    service = _service_with_failing_live_poll(tmp_path, FileNotFoundError("[Errno 2] No such file"))
    service.tick()
    err = capsys.readouterr().err
    assert "LIVE_TRANSCRIPTION_SITE must be the site name" in err
    service.close()


def test_non_missing_failure_message_does_not_blame_the_config(tmp_path, capsys):
    """The torn-sidecar JSONDecodeError from the real deployment was
    reported with a "is LIVE_TRANSCRIPTION_SITE the site name...?" hint,
    which sent the operator to debug a setting that was correct all along.
    A failure that isn't a missing file means the ring buffer *is* there."""
    import json as _json

    service = _service_with_failing_live_poll(
        tmp_path, _json.JSONDecodeError("Expecting value", "", 0)
    )
    service.tick()
    err = capsys.readouterr().err
    assert "not a LIVE_TRANSCRIPTION_SITE/_CHANNEL problem" in err
    assert "must be the site name" not in err
    service.close()


def test_persistent_live_segmenter_failure_never_crashes_tick(tmp_path):
    """The misconfiguration case (wrong site name, never recovers) --
    `tick()` must stay callable indefinitely, since it also drives the
    core ZCZC/EOM alert-capture timeout check (see its own docstring)."""

    class _AlwaysFails:
        def __init__(self, site, channel, ring_reader, output_dir):
            pass

        def poll(self):
            raise FileNotFoundError("permanently missing")

    publisher = FakePublisher()
    service = SegmentCaptureService(
        ring_buffer_dir=tmp_path,
        output_dir=tmp_path / "captures",
        publisher=publisher,
        live_channel=("home", "WX7"),
        live_segmenter_factory=_AlwaysFails,
        ring_reader_factory=FakeRingReader,
    )
    for _ in range(10):
        service.tick()  # must never raise
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


class _StatsLiveSegmenter:
    """Reports fixed stats, like a real `LiveSegmenter` accumulating frame
    RMS -- these tests cover the status-line reporting in `service.py`, not
    the VAD measurement itself."""

    rms_threshold = 0.02

    def __init__(self, site, channel, ring_reader, output_dir, **kwargs):
        self.kwargs = kwargs
        self._stats = None

    def set_stats(self, **fields):
        from segment_capture.live_segmenter import LiveSegmenterStats

        self._stats = LiveSegmenterStats(**fields)

    def poll(self):
        return []

    def drain_stats(self):
        from segment_capture.live_segmenter import LiveSegmenterStats

        stats, self._stats = self._stats or LiveSegmenterStats(), None
        return stats


def _live_service(tmp_path, clock, interval=60.0):
    return SegmentCaptureService(
        ring_buffer_dir=tmp_path,
        output_dir=tmp_path / "captures",
        publisher=FakePublisher(),
        live_channel=("PDX", "WX7"),
        live_segmenter_factory=_StatsLiveSegmenter,
        ring_reader_factory=FakeRingReader,
        live_status_interval_seconds=interval,
        now_fn=lambda: clock[0],
    )


def test_live_status_line_is_not_printed_before_the_interval(tmp_path, capsys):
    clock = [1000.0]
    service = _live_service(tmp_path, clock)
    service.tick()
    clock[0] += 30.0
    service.tick()
    assert "last" not in capsys.readouterr().err
    service.close()


def test_live_status_line_reports_levels_against_the_threshold(tmp_path, capsys):
    clock = [1000.0]
    service = _live_service(tmp_path, clock)
    service.tick()  # establishes the window start
    service._live_segmenter.set_stats(frames=100, speech_frames=40, peak_rms=0.09, sum_rms=3.0, chunks=2)
    clock[0] += 60.0
    service.tick()

    err = capsys.readouterr().err
    assert "live PDX/WX7 last 60s" in err
    assert "rms mean 0.0300 peak 0.0900 vs threshold 0.0200" in err
    assert "40% of audio counted as speech" in err
    assert "2 chunk(s) sent" in err
    service.close()


def test_live_status_line_calls_out_a_threshold_set_too_high(tmp_path, capsys):
    """The most likely silent failure: audio is present but never clears the
    uncalibrated default threshold, so nothing is ever cut and nothing is
    ever logged. The status line must name the fix, not just the numbers."""
    clock = [1000.0]
    service = _live_service(tmp_path, clock)
    service.tick()
    service._live_segmenter.set_stats(frames=100, speech_frames=0, peak_rms=0.004, sum_rms=0.2, chunks=0)
    clock[0] += 60.0
    service.tick()

    err = capsys.readouterr().err
    assert "nothing above the threshold" in err
    assert "lower LIVE_TRANSCRIPTION_RMS_THRESHOLD toward 0.0040" in err
    service.close()


def test_live_recovery_is_logged(tmp_path, capsys):
    """A failure that resolves used to do so silently, leaving an operator
    who'd seen the startup warning unable to tell whether it had."""
    failing = {"yes": True}

    class _FlakySegmenter:
        rms_threshold = 0.02

        def __init__(self, site, channel, ring_reader, output_dir, **kwargs):
            pass

        def poll(self):
            if failing["yes"]:
                raise FileNotFoundError("not yet")
            return []

        def drain_stats(self):
            from segment_capture.live_segmenter import LiveSegmenterStats

            return LiveSegmenterStats()

    service = SegmentCaptureService(
        ring_buffer_dir=tmp_path,
        output_dir=tmp_path / "captures",
        publisher=FakePublisher(),
        live_channel=("PDX", "WX7"),
        live_segmenter_factory=_FlakySegmenter,
        ring_reader_factory=FakeRingReader,
    )
    service.tick()
    assert "can't read the ring buffer" in capsys.readouterr().err

    failing["yes"] = False
    service.tick()
    assert "live transcription reading PDX/WX7 now" in capsys.readouterr().err
    service.close()


def test_live_segmenter_options_are_passed_through(tmp_path):
    service = SegmentCaptureService(
        ring_buffer_dir=tmp_path,
        output_dir=tmp_path / "captures",
        publisher=FakePublisher(),
        live_channel=("PDX", "WX7"),
        live_segmenter_factory=_StatsLiveSegmenter,
        ring_reader_factory=FakeRingReader,
        live_segmenter_options={"rms_threshold": 0.005, "min_chunk_seconds": 2.0},
    )
    service.tick()
    assert service._live_segmenter.kwargs == {"rms_threshold": 0.005, "min_chunk_seconds": 2.0}
    service.close()
