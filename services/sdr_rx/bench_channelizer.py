"""CPU throughput benchmark for the capture pipeline -- `make bench-channelizer`.

Design doc hazard #2 calls out ~15% of a Pi core as the bar for a batched
channelizer implementation. This script reports achieved samples/sec and
the real-time margin at the design sample rate (1.2 MS/s) so that number
can be checked on target hardware, not just assumed.

Reports two figures, because the channelizer stopped being the whole story
once it was made to stop dominating: the channelizer alone (the number
hazard #2's bar is about) and `DevicePipeline.process()` end to end (the
number that decides whether a dongle keeps up). The second is what to
watch -- discriminator, resampling, voice-band filter and squelch run
seven times per chunk, once per NWR channel, and together they cost more
than the channelizer does now.

Samples are `complex64`, matching what `capture.py` asks SoapySDR for
(`SOAPY_SDR_CF32`) and what the pipeline therefore carries end to end; a
`complex128` benchmark would measure a precision this system never runs at
(see channelizer.py's "Sample precision").
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import numpy as np

from sdr_rx.channelizer import PolyphaseChannelizer
from sdr_rx.channels import nwr_bins
from sdr_rx.pipeline import DevicePipeline
from sdr_rx.ring_buffer import ChannelRingBuffer

FS = 1_200_000.0
CHUNK_SECONDS = 0.1
N_CHUNKS = 50


class _NullPublisher:
    """Stands in for the ZMQ publisher: this measures DSP cost, and a real
    PUB socket would fold in whatever the subscribers are doing."""

    def publish(self, topic, site, channel, sample_rate_hz, pcm) -> None:
        pass


def _report(label: str, elapsed: float, total_samples: int) -> None:
    samples_per_sec = total_samples / elapsed
    realtime_factor = samples_per_sec / FS
    print(f"{label}:")
    print(f"  processed {total_samples:,} samples in {elapsed:.3f}s")
    print(f"  throughput: {samples_per_sec:,.0f} samples/sec")
    print(f"  real-time factor: {realtime_factor:.2f}x  ({100 / realtime_factor:.1f}% of one core per dongle)")


def main() -> None:
    rng = np.random.default_rng(0)
    chunk_len = int(FS * CHUNK_SECONDS)
    x = (rng.normal(size=chunk_len) + 1j * rng.normal(size=chunk_len)).astype(np.complex64)
    total_samples = chunk_len * N_CHUNKS

    ch = PolyphaseChannelizer()
    ch.process(x)  # warm up (filter history, workspace allocation, first-call overhead)
    start = time.perf_counter()
    for _ in range(N_CHUNKS):
        ch.process(x)
    _report("channelizer alone", time.perf_counter() - start, total_samples)

    with tempfile.TemporaryDirectory() as tmp:
        ring_buffers = {b.channel: ChannelRingBuffer(Path(tmp), b.channel) for b in nwr_bins()}
        pipeline = DevicePipeline("bench", _NullPublisher(), ring_buffers)
        pipeline.process(x)  # warm up
        start = time.perf_counter()
        for _ in range(N_CHUNKS):
            pipeline.process(x)
        elapsed = time.perf_counter() - start
    print()
    _report("full pipeline (channelize + 7 channels' audio path)", elapsed, total_samples)


if __name__ == "__main__":
    main()
