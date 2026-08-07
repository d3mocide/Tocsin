# sdr-rx

Owns the RTL-SDR dongle(s). Custom SoapySDR + numpy polyphase channelizer --
see `../../docs/` and the repo root README for the full design.

## Status

Milestone 1 only: the standalone 48-bin odd-stacked polyphase channelizer
(`src/sdr_rx/channelizer.py`), DC blocker, and channel/bin mapping, with
unit tests. SoapySDR device capture, ZMQ publishing, and the tmpfs ring
buffer are not yet implemented (milestones after channelizer verification
per the repo root README build order).

## Development

```sh
uv sync
uv run pytest
```
