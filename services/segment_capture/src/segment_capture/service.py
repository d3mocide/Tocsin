"""Wires the per-(site, channel) boundary-detecting multimon-ng subprocess,
ring-buffer reader, and recorder into one capture pipeline (design doc §4).
"""

from __future__ import annotations

from pathlib import Path

from .boundary import is_eom, parse_message_start
from .bus import CapturePublisher
from .multimon import MultimonProcess
from .recorder import DEFAULT_HARD_TIMEOUT_SECONDS, DEFAULT_PREROLL_SECONDS, SegmentRecorder
from .ring_reader import RingBufferReader


class SegmentCaptureService:
    """One boundary detector per (site, channel), created lazily on first
    audio for that key; a `SegmentRecorder` only exists while a message is
    actually in progress for that key."""

    def __init__(
        self,
        ring_buffer_dir: Path,
        output_dir: Path,
        publisher: CapturePublisher,
        multimon_command: list[str] | None = None,
        preroll_seconds: float = DEFAULT_PREROLL_SECONDS,
        hard_timeout_seconds: float = DEFAULT_HARD_TIMEOUT_SECONDS,
        recorder_factory=SegmentRecorder,
        ring_reader_factory=RingBufferReader,
    ):
        self._ring_buffer_dir = ring_buffer_dir
        self._output_dir = output_dir
        self._publisher = publisher
        self._multimon_command = multimon_command
        self._preroll_seconds = preroll_seconds
        self._hard_timeout_seconds = hard_timeout_seconds
        self._recorder_factory = recorder_factory
        self._ring_reader_factory = ring_reader_factory
        self._detectors: dict[tuple[str, str], MultimonProcess] = {}
        self._recorders: dict[tuple[str, str], SegmentRecorder] = {}

    def feed(self, site: str, channel: str, pcm_bytes: bytes) -> None:
        key = (site, channel)
        if key not in self._detectors:
            self._detectors[key] = MultimonProcess(command=self._multimon_command)
        detector = self._detectors[key]
        detector.write(pcm_bytes)
        for line in detector.poll_lines():
            self._handle_line(key, line)
        recorder = self._recorders.get(key)
        if recorder is not None:
            recorder.poll()

    def tick(self) -> None:
        """Call on every main-loop iteration, whether or not `feed()` ran --
        a capture whose channel stops producing new audio (e.g. sdr-rx died
        mid-message) still needs to hit its hard timeout instead of hanging
        forever waiting for a `feed()` call that may never come."""
        for key in list(self._recorders):
            recorder = self._recorders.get(key)
            if recorder is not None and recorder.timed_out():
                self._finalize(key, timed_out=True)

    def _handle_line(self, key: tuple[str, str], line: str) -> None:
        site, channel = key
        if key not in self._recorders:
            message_start = parse_message_start(line)
            if message_start is not None:
                ring_reader = self._ring_reader_factory(self._ring_buffer_dir / site, channel)
                self._recorders[key] = self._recorder_factory(
                    site,
                    channel,
                    message_start,
                    ring_reader,
                    self._output_dir,
                    preroll_seconds=self._preroll_seconds,
                    hard_timeout_seconds=self._hard_timeout_seconds,
                )
            return
        if is_eom(line):
            self._finalize(key, timed_out=False)

    def _finalize(self, key: tuple[str, str], timed_out: bool) -> None:
        recorder = self._recorders.pop(key)
        result = recorder.finalize(timed_out=timed_out)
        self._publisher.publish(result)

    def close(self) -> None:
        for detector in self._detectors.values():
            detector.close()
