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

import subprocess


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
    Vorbis stream to an Icecast mountpoint."""

    def __init__(self, command: list[str]):
        self._process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    def write(self, pcm_bytes: bytes) -> None:
        assert self._process.stdin is not None
        self._process.stdin.write(pcm_bytes)
        self._process.stdin.flush()

    def is_alive(self) -> bool:
        return self._process.poll() is None

    def close(self) -> None:
        if self._process.stdin is not None:
            try:
                self._process.stdin.close()
            except OSError:
                pass
        self._process.terminate()
        try:
            self._process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
