"""Wires the ZMQ subscriber to one ffmpeg feeder per (site, channel)."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .feeder import FFmpegFeeder, build_ffmpeg_command, icecast_source_url, mount_name
from .metadata import MetadataConfig

# How long to back off after a feeder dies before spawning a replacement
# ffmpeg for that mount. Long enough that a genuinely broken mount (bad
# source password, unreachable Icecast) doesn't spin up an ffmpeg process
# on every ~55ms audio chunk; short enough that a transient death (Icecast
# restart, a dropped TCP connection, ffmpeg getting OOM-killed under load)
# heals within about one heartbeat cycle instead of leaving the mount
# "FEEDER DEAD" for the rest of the process's uptime (see
# `docs/design/tracking.md`: this is what previously made a mountpoint
# permanently dead after a single ffmpeg crash, days into a run, with no
# way to recover short of restarting live_audio).
DEFAULT_RETRY_INTERVAL_SECONDS = 30.0


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
    shouldn't take every other channel's stream down. A dead feeder is
    retried periodically (`retry_interval_seconds`) rather than abandoned
    forever, since ffmpeg/Icecast can die for reasons that later clear up
    on their own (a network blip, an Icecast restart, an OOM kill) and
    live_audio itself is meant to run for days between restarts.

    `allowed_channels`, when given, gates which channels ever get a feeder
    at all -- `None` (the default) streams every channel sdr-rx publishes,
    same as before this existed. Most deployments only have usable signal
    on one or two of the seven NWR channels; the other five/six otherwise
    ran a permanent ffmpeg/vorbis encode and Icecast source connection for
    no listener, ever (see `docs/design/tracking.md`'s entry on this). The
    gate lives here rather than at the ZMQ subscribe level so SAME decode
    and the alert ring buffer -- sdr-rx's other two consumers of the same
    per-channel audio -- are entirely unaffected; this only ever narrows
    what live_audio itself does with a channel it still receives."""

    def __init__(
        self,
        icecast: IcecastConfig,
        metadata: MetadataConfig | None = None,
        feeder_factory=FFmpegFeeder,
        allowed_channels: frozenset[str] | None = None,
        retry_interval_seconds: float = DEFAULT_RETRY_INTERVAL_SECONDS,
        now_fn=time.monotonic,
    ):
        self._icecast = icecast
        self._metadata = metadata or MetadataConfig()
        self._feeder_factory = feeder_factory
        self._allowed_channels = allowed_channels
        self._retry_interval_seconds = retry_interval_seconds
        self._now = now_fn
        self._feeders: dict[tuple[str, str], FFmpegFeeder] = {}
        self._dead: set[tuple[str, str]] = set()
        self._retry_at: dict[tuple[str, str], float] = {}

    def feed(self, site: str, channel: str, sample_rate_hz: int, pcm_bytes: bytes) -> None:
        if self._allowed_channels is not None and channel not in self._allowed_channels:
            return
        key = (site, channel)
        feeder = self._feeders.get(key)
        if feeder is None:
            retry_at = self._retry_at.get(key)
            if retry_at is not None and self._now() < retry_at:
                return  # still backing off from the last death -- don't spawn ffmpeg on every chunk
            url = icecast_source_url(
                self._icecast.host, self._icecast.port, self._icecast.user, self._icecast.password, mount_name(site, channel)
            )
            meta = self._metadata.resolve(site, channel)
            feeder = self._feeder_factory(
                build_ffmpeg_command(
                    url,
                    sample_rate_hz,
                    stream_name=meta.name,
                    stream_description=meta.description,
                    stream_genre=meta.genre,
                )
            )
            self._feeders[key] = feeder
        if not feeder.is_alive():
            feeder.close()
            del self._feeders[key]
            self._dead.add(key)
            self._retry_at[key] = self._now() + self._retry_interval_seconds
            return
        self._dead.discard(key)
        feeder.write(pcm_bytes)

    def mount_urls(self, icecast_public_url: str) -> dict[tuple[str, str], str]:
        return {key: f"{icecast_public_url}{mount_name(*key)}" for key in self._feeders}

    def mounts(self) -> list[dict]:
        """Every (site, channel) this process has ever fed, with whether
        its ffmpeg is still alive. Reported on the liveness heartbeat so
        the UI can list playable streams without querying Icecast's admin
        interface -- and, more usefully, can still show a channel whose
        feeder died, which Icecast itself would simply stop listing."""
        live = [{"site": s, "channel": c, "mount": mount_name(s, c), "alive": True} for s, c in sorted(self._feeders)]
        dead = [{"site": s, "channel": c, "mount": mount_name(s, c), "alive": False} for s, c in sorted(self._dead)]
        return live + dead

    def close(self) -> None:
        for feeder in self._feeders.values():
            feeder.close()
