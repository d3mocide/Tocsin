"""Wires the ZMQ subscriber to one ffmpeg feeder per (site, channel)."""

from __future__ import annotations

from dataclasses import dataclass

from .feeder import FFmpegFeeder, build_ffmpeg_command, icecast_source_url, mount_name


@dataclass(frozen=True)
class IcecastConfig:
    host: str
    port: int
    user: str
    password: str


class Streamer:
    """Creates one FFmpegFeeder per (site, channel) lazily, the first time
    audio for that key arrives, and stops feeding (rather than crashing the
    whole process) if that channel's ffmpeg dies -- one bad mountpoint
    shouldn't take every other channel's stream down."""

    def __init__(self, icecast: IcecastConfig, feeder_factory=FFmpegFeeder):
        self._icecast = icecast
        self._feeder_factory = feeder_factory
        self._feeders: dict[tuple[str, str], FFmpegFeeder] = {}
        self._dead: set[tuple[str, str]] = set()

    def feed(self, site: str, channel: str, sample_rate_hz: int, pcm_bytes: bytes) -> None:
        key = (site, channel)
        if key in self._dead:
            return
        feeder = self._feeders.get(key)
        if feeder is None:
            url = icecast_source_url(
                self._icecast.host, self._icecast.port, self._icecast.user, self._icecast.password, mount_name(site, channel)
            )
            feeder = self._feeder_factory(build_ffmpeg_command(url, sample_rate_hz))
            self._feeders[key] = feeder
        if not feeder.is_alive():
            self._dead.add(key)
            del self._feeders[key]
            return
        feeder.write(pcm_bytes)

    def mount_urls(self, icecast_public_url: str) -> dict[tuple[str, str], str]:
        return {key: f"{icecast_public_url}{mount_name(*key)}" for key in self._feeders}

    def close(self) -> None:
        for feeder in self._feeders.values():
            feeder.close()
