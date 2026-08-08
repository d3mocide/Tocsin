"""Reads the latest spectrum snapshot `sdr_rx` publishes per site
(`tocsin:spectrum:<site>`, a plain Redis key -- see
`sdr_rx.redis_sink.RedisSpectrumSink`'s docstring for why this is a
snapshot key, not a stream). No Postgres involved: a waterfall display
only ever wants "right now," never history to replay.
"""

from __future__ import annotations

import json

KEY_PREFIX = "tocsin:spectrum"


async def get_spectrum(redis_client, site: str) -> dict | None:
    raw = await redis_client.get(f"{KEY_PREFIX}:{site}")
    if raw is None:
        return None
    return json.loads(raw)


async def list_spectrum_sites(redis_client) -> list[str]:
    keys = await redis_client.keys(f"{KEY_PREFIX}:*")
    prefix_len = len(KEY_PREFIX) + 1
    return [key[prefix_len:] for key in keys]
