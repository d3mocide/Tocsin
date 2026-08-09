"""ffmpeg subprocess wrapper: pipe raw s16le PCM to Icecast as an Ogg/Vorbis
source stream, one mountpoint per (site, channel).

Icecast over MediaMTX for this v1 (design doc §3 Phase 3 open item): the
design doc calls Icecast "trivial" against MediaMTX's sub-second-but-more-
moving-parts WebRTC path, and for a hardware bring-up/tuning tool, "works
today" beats "lower latency" -- revisit if 5-10s of delay turns out to
matter for tuning by ear.

The command is injectable so this is testable without ffmpeg installed.
"""

from __future__ import annotations

import queue
import subprocess
import threading

# ~2s of audio at the ~55ms chunk size sdr-rx's pipeline publishes (see
# sdr_rx.pipeline.DevicePipeline.process): enough slack to ride out a brief
# network stall to Icecast without the buffer growing unbounded or adding
# noticeable extra latency to an already-not-low-latency stream (feeder.py's
# module docstring).
DEFAULT_QUEUE_MAXSIZE = 40


def mount_name(site: str, channel: str) -> str:
    return f"/{site}-{channel}.ogg"


def icecast_source_url(host: str, port: int, user: str, password: str, mount: str) -> str:
    return f"icecast://{user}:{password}@{host}:{port}{mount}"


def build_ffmpeg_command(
    icecast_url: str,
    sample_rate_hz: int,
    *,
    stream_name: str | None = None,
    stream_description: str | None = None,
    stream_genre: str | None = None,
) -> list[str]:
    command = [
        "ffmpeg",
        "-loglevel", "error",
        "-f", "s16le",
        "-ar", str(sample_rate_hz),
        "-ac", "1",
        "-i", "pipe:0",
        "-c:a", "libvorbis",
        "-b:a", "32k",
        "-content_type", "application/ogg",
    ]  # fmt: skip
    # -ice_name/-ice_description/-ice_genre are ffmpeg's icecast protocol
    # options (not codec options), only meaningful right before the output
    # URL -- same mechanism as -content_type above.
    if stream_name:
        command += ["-ice_name", stream_name]
    if stream_description:
        command += ["-ice_description", stream_description]
    if stream_genre:
        command += ["-ice_genre", stream_genre]
    command += ["-f", "ogg", icecast_url]
    return command


class FFmpegFeeder:
    """One running ffmpeg subprocess pushing PCM written to it as an Ogg/
    Vorbis stream to an Icecast mountpoint.

    The actual `stdin.write()` runs on a dedicated background thread behind
    a small bounded queue, not on the caller's thread. Without that, a
    network stall between ffmpeg and Icecast blocks ffmpeg's stdin pipe,
    which blocks `write()`, which -- upstream, in `Streamer.feed()` --
    blocks whatever's calling it: `live_audio`'s single-threaded ZMQ receive
    loop. Stalling that loop is what actually caused audible cutouts, since
    it stops draining the ZMQ SUB socket and its receive buffer starts
    silently dropping frames once full (see `subscriber.py`'s docstring on
    why that drop-under-load is deliberate for *that* buffer -- but a
    network blip shouldn't be what triggers it). `write()` here is
    non-blocking instead: once the queue is full, the oldest buffered chunk
    is dropped to make room for the newest, since for a live feed skipping
    old audio beats falling behind.
    """

    def __init__(self, command: list[str], queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE):
        self._process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=queue_maxsize)
        self._writer_thread = threading.Thread(target=self._run_writer, daemon=True)
        self._writer_thread.start()

    def _run_writer(self) -> None:
        assert self._process.stdin is not None
        while True:
            chunk = self._queue.get()
            if chunk is None:
                return
            try:
                self._process.stdin.write(chunk)
                self._process.stdin.flush()
            except (BrokenPipeError, OSError):
                return

    def write(self, pcm_bytes: bytes) -> None:
        try:
            self._queue.put_nowait(pcm_bytes)
        except queue.Full:
            try:
                self._queue.get_nowait()  # drop the oldest buffered chunk
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(pcm_bytes)
            except queue.Full:
                pass  # lost the race with the writer thread -- fine to skip this chunk

    def is_alive(self) -> bool:
        return self._process.poll() is None

    def close(self) -> None:
        self._queue.put(None)
        # Give the writer thread a chance to drain whatever's still queued
        # and exit on its own first -- the common case, done in well under
        # this timeout. Only if it's actually stuck inside a blocking
        # stdin.write() (e.g. ffmpeg wedged on a dead Icecast connection) do
        # we terminate ffmpeg early to unstick it: that makes the pending
        # write fail rather than hang, freeing the thread to reach the
        # sentinel check and return.
        self._writer_thread.join(timeout=0.5)
        if self._writer_thread.is_alive():
            self._process.terminate()
            self._writer_thread.join(timeout=2.0)
        if self._process.stdin is not None:
            try:
                self._process.stdin.close()
            except OSError:
                pass
        try:
            self._process.terminate()
        except OSError:
            pass  # already exited and reaped by the stuck-writer branch above
        try:
            self._process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
