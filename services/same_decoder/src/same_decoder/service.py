"""Wires the ZMQ subscriber, per-(site, channel) multimon-ng subprocess,
header parsing, tier lookup, and dedup into one decode pipeline (design doc
§4)."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Protocol

from .dedup import DEFAULT_TTL_SECONDS, HeaderDeduplicator
from .multimon import MultimonProcess
from .parser import parse_same_header
from .tiers import TierTable


@dataclass(frozen=True)
class SameEvent:
    site: str
    channel: str
    timestamp_ns: int
    event_code: str
    event_name: str
    tier: str
    fips_codes: tuple[str, ...]
    originator: str
    callsign: str
    purge_minutes: int
    raw_header: str


class EventSink(Protocol):
    def record(self, event: SameEvent) -> None: ...


class LoggingEventSink:
    """Default sink: one JSON line per event on stdout. Structured events
    don't have a Redis Streams/fusion consumer yet (that's Phase 5) -- this
    is the seam a real publisher drops into later without touching Decoder."""

    def record(self, event: SameEvent) -> None:
        print(json.dumps(asdict(event)), flush=True)


class Decoder:
    """One multimon-ng subprocess + dedup window per (site, channel),
    created lazily as audio for a new key arrives."""

    def __init__(
        self,
        tiers: TierTable,
        sink: EventSink | None = None,
        multimon_command: list[str] | None = None,
        dedup_ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ):
        self._tiers = tiers
        self._sink = sink or LoggingEventSink()
        self._multimon_command = multimon_command
        self._dedup_ttl_seconds = dedup_ttl_seconds
        self._processes: dict[tuple[str, str], MultimonProcess] = {}
        self._dedup: dict[tuple[str, str], HeaderDeduplicator] = {}

    def feed(self, site: str, channel: str, pcm_bytes: bytes) -> None:
        key = (site, channel)
        if key not in self._processes:
            self._processes[key] = MultimonProcess(command=self._multimon_command)
            self._dedup[key] = HeaderDeduplicator(ttl_seconds=self._dedup_ttl_seconds)
        process = self._processes[key]
        process.write(pcm_bytes)
        for line in process.poll_lines():
            self._handle_line(site, channel, line)

    def _handle_line(self, site: str, channel: str, line: str) -> None:
        header = parse_same_header(line)
        if header is None:
            return
        if self._dedup[(site, channel)].is_duplicate(header):
            return
        name, tier = self._tiers.lookup(header.event_code)
        self._sink.record(
            SameEvent(
                site=site,
                channel=channel,
                timestamp_ns=time.time_ns(),
                event_code=header.event_code,
                event_name=name,
                tier=tier,
                fips_codes=header.fips_codes,
                originator=header.originator,
                callsign=header.callsign,
                purge_minutes=header.purge_minutes,
                raw_header=header.raw,
            )
        )

    def close(self) -> None:
        for process in self._processes.values():
            process.close()
