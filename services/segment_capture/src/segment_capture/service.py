"""Wires the per-(site, channel) boundary-detecting multimon-ng subprocess,
ring-buffer reader, and recorder into one capture pipeline (design doc §4).
"""

from __future__ import annotations

import sys
from pathlib import Path

from .boundary import is_eom, parse_message_start
from .bus import CapturePublisher
from .live_segmenter import LiveSegmenter
from .multimon import MultimonProcess
from .recorder import DEFAULT_HARD_TIMEOUT_SECONDS, DEFAULT_PREROLL_SECONDS, SegmentRecorder
from .ring_reader import RingBufferReader
from .tiers import TierTable


class SegmentCaptureService:
    """One boundary detector per (site, channel), created lazily on first
    audio for that key; a `SegmentRecorder` only exists while a message is
    actually in progress for that key.

    `live_channel`, when given, additionally runs one `LiveSegmenter` on
    that single (site, channel) -- continuous, VAD-cut transcription
    capture, independent of the ZCZC/EOM detector above (design doc's
    live-transcription addendum). Deliberately one channel, not "every
    channel that has audio": `stt_worker`'s CPU budget (design doc §6) is
    sized for occasional alert captures, not continuous inference on all
    seven NWR channels at once."""

    def __init__(
        self,
        ring_buffer_dir: Path,
        output_dir: Path,
        publisher: CapturePublisher,
        tiers: TierTable | None = None,
        multimon_command: list[str] | None = None,
        preroll_seconds: float = DEFAULT_PREROLL_SECONDS,
        hard_timeout_seconds: float = DEFAULT_HARD_TIMEOUT_SECONDS,
        recorder_factory=SegmentRecorder,
        ring_reader_factory=RingBufferReader,
        live_channel: tuple[str, str] | None = None,
        live_segmenter_factory=LiveSegmenter,
        live_output_dir: Path | None = None,
    ):
        self._ring_buffer_dir = ring_buffer_dir
        self._output_dir = output_dir
        self._publisher = publisher
        # Optional, not required, unlike same_decoder.Decoder's `tiers` --
        # segment_capture's own tests predate tier threading and construct
        # this without a data/ directory available; an empty TierTable
        # just falls back to Tier B for every code (TierTable's own
        # "unrecognized code" behavior), which is a safe default here since
        # nothing downstream silently escalates on it.
        self._tiers = tiers or TierTable({})
        self._multimon_command = multimon_command
        self._preroll_seconds = preroll_seconds
        self._hard_timeout_seconds = hard_timeout_seconds
        self._recorder_factory = recorder_factory
        self._ring_reader_factory = ring_reader_factory
        self._detectors: dict[tuple[str, str], MultimonProcess] = {}
        self._recorders: dict[tuple[str, str], SegmentRecorder] = {}
        self._live_channel = live_channel
        self._live_segmenter_factory = live_segmenter_factory
        self._live_output_dir = live_output_dir or output_dir
        self._live_segmenter: LiveSegmenter | None = None
        self._live_warned = False

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
        self._poll_live()

    def _poll_live(self) -> None:
        if self._live_channel is None:
            return
        site, channel = self._live_channel
        if self._live_segmenter is None:
            ring_reader = self._ring_reader_factory(self._ring_buffer_dir / site, channel)
            self._live_segmenter = self._live_segmenter_factory(site, channel, ring_reader, self._live_output_dir)
        try:
            results = self._live_segmenter.poll()
        except Exception as exc:
            # The configured (site, channel)'s ring buffer isn't readable
            # yet -- either sdr-rx hasn't created it (a real startup race:
            # this process and sdr-rx's own capture loop start together),
            # or LIVE_TRANSCRIPTION_SITE/_CHANNEL doesn't name a real
            # (site, channel) sdr-rx is actually running.
            # LIVE_TRANSCRIPTION_SITE is the site *name* from
            # SDR_RX_DEVICES (e.g. "home"), never the dongle serial
            # number -- a mismatch here used to crash-loop this whole
            # process, taking the core ZCZC/EOM alert-capture path down
            # with it, since both run in the same service. An optional,
            # off-by-default addendum must never do that: log once and
            # keep retrying on the next tick() instead.
            if not self._live_warned:
                print(
                    f"segment-capture: live transcription can't read the ring buffer for "
                    f"{site}/{channel} ({exc!r}) -- is LIVE_TRANSCRIPTION_SITE the site name "
                    "from SDR_RX_DEVICES, not a serial number? Will keep retrying.",
                    file=sys.stderr,
                )
                self._live_warned = True
            return
        self._live_warned = False
        for result in results:
            self._publisher.publish_live(result)

    def _handle_line(self, key: tuple[str, str], line: str) -> None:
        site, channel = key
        if key not in self._recorders:
            message_start = parse_message_start(line)
            if message_start is not None:
                ring_reader = self._ring_reader_factory(self._ring_buffer_dir / site, channel)
                _name, tier = self._tiers.lookup(message_start.event_code)
                self._recorders[key] = self._recorder_factory(
                    site,
                    channel,
                    message_start,
                    ring_reader,
                    self._output_dir,
                    tier=tier,
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
