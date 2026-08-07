"""CPU throughput benchmark for the channelizer -- `make bench-channelizer`.

Design doc hazard #2 calls out ~15% of a Pi core as the bar for a batched
implementation. This script reports achieved samples/sec and the
real-time margin at the design sample rate (1.2 MS/s) so that number can
be checked on target hardware, not just assumed.
"""

from __future__ import annotations

import time

import numpy as np

from sdr_rx.channelizer import PolyphaseChannelizer

FS = 1_200_000.0


def main() -> None:
    rng = np.random.default_rng(0)
    chunk_seconds = 0.1
    chunk_len = int(FS * chunk_seconds)
    n_chunks = 50
    x = (rng.normal(size=chunk_len) + 1j * rng.normal(size=chunk_len)).astype(complex)

    ch = PolyphaseChannelizer()
    ch.process(x)  # warm up (filter history, first-call overhead)

    start = time.perf_counter()
    for _ in range(n_chunks):
        ch.process(x)
    elapsed = time.perf_counter() - start

    total_samples = chunk_len * n_chunks
    samples_per_sec = total_samples / elapsed
    realtime_factor = samples_per_sec / FS

    print(f"processed {total_samples:,} samples in {elapsed:.3f}s")
    print(f"throughput: {samples_per_sec:,.0f} samples/sec")
    print(f"real-time factor: {realtime_factor:.2f}x (>1.0 means faster than the 1.2 MS/s input rate)")


if __name__ == "__main__":
    main()
