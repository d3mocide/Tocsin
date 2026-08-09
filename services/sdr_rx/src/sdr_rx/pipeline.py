"""Per-device processing pipeline: raw samples -> DC block -> channelizer ->
per-channel discriminator -> ring buffer + ZMQ publish + health sample.

Takes anything with a `read_chunk() -> np.ndarray` method -- `SoapySDRDevice`
on target hardware, a synthetic generator in tests -- so the whole pipeline
except device I/O itself is exercisable without RTL-SDR hardware.
"""

from __future__ import annotations

from typing import Callable, Protocol

import numpy as np

from .audio_conditioning import SQUELCH_OPEN_DB, Squelch, VoiceBandFilter
from .bus import TOPIC_SAME, TOPIC_STT
from .channelizer import PolyphaseChannelizer
from .channels import nwr_bins
from .dc_block import DCBlocker
from .discriminator import FMDiscriminator
from .health import HealthTracker
from .resample import to_multimon_rate, to_s16le, to_stt_rate
from .ring_buffer import ChannelRingBuffer
from .spectrum import SpectrumTracker


class SampleSource(Protocol):
    def read_chunk(self) -> np.ndarray: ...


class ChannelPublisher(Protocol):
    def publish(self, topic: str, site: str, channel: str, sample_rate_hz: int, pcm: np.ndarray) -> None: ...


class _ChannelState:
    """Per-NWR-channel state carried across `process()` calls."""

    def __init__(self, channel: str, ring_buffer: ChannelRingBuffer, squelch_open_db: float):
        self.channel = channel
        self.discriminator = FMDiscriminator()
        self.ring_buffer = ring_buffer
        self.voice_filter = VoiceBandFilter()
        self.squelch = Squelch(open_db=squelch_open_db)


class DevicePipeline:
    """One dongle's full path: DC block -> channelize -> per-channel discriminate
    -> ring-buffer + publish + health, for all seven NWR channels."""

    def __init__(
        self,
        site: str,
        publisher: ChannelPublisher,
        ring_buffers: dict[str, ChannelRingBuffer],
        health: HealthTracker | None = None,
        spectrum: SpectrumTracker | None = None,
        channelizer: PolyphaseChannelizer | None = None,
        dc_blocker: DCBlocker | None = None,
        squelch_open_db: float = SQUELCH_OPEN_DB,
    ):
        self.site = site
        self._publisher = publisher
        self._dc_blocker = dc_blocker or DCBlocker()
        self._channelizer = channelizer or PolyphaseChannelizer()
        self._health = health or HealthTracker()
        self._spectrum = spectrum or SpectrumTracker(site)
        self._bins = nwr_bins()
        missing = [b.channel for b in self._bins if b.channel not in ring_buffers]
        if missing:
            raise ValueError(f"missing ring buffers for channels: {missing}")
        self._channels = {
            b.channel: _ChannelState(b.channel, ring_buffers[b.channel], squelch_open_db) for b in self._bins
        }

    def process(self, samples: np.ndarray) -> None:
        cleaned = self._dc_blocker.process(samples)
        spectrum = self._channelizer.process(cleaned)  # (n_frames, num_bins)
        if spectrum.shape[0] == 0:
            return
        self._spectrum.sample(spectrum)
        for b in self._bins:
            state = self._channels[b.channel]
            bin_samples = spectrum[:, b.k % self._channelizer.num_bins]
            audio = state.discriminator.process(bin_samples)
            if audio.size == 0:
                continue
            state.ring_buffer.write(audio)
            self._health.sample(self.site, b.channel, audio)
            self._publisher.publish(TOPIC_SAME, self.site, b.channel, 22050, to_s16le(to_multimon_rate(audio)))
            # Squelch + voice-band filter apply only to this feed (live_audio's
            # Icecast stream) -- SAME decode above and the ring buffer
            # segment_capture reads alert audio from both stay on raw `audio`,
            # untouched (audio_conditioning.py's docstring).
            live_audio = state.voice_filter.process(audio) * state.squelch.envelope(audio)
            self._publisher.publish(TOPIC_STT, self.site, b.channel, 16000, to_s16le(to_stt_rate(live_audio)))

    def run_forever(self, source: SampleSource, stop: Callable[[], bool] | None = None) -> None:
        while stop is None or not stop():
            chunk = source.read_chunk()
            if chunk.size:
                self.process(chunk)
