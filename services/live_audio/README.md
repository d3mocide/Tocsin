# live-audio

Subscribes to `sdr-rx`'s `stt.<site>.<channel>` ZMQ topic (16 kHz s16le
mono -- the same rate contract `stt-worker` will use) and pushes each
channel as its own Ogg/Vorbis stream to Icecast via ffmpeg, so a channel can
be confirmed by ear (tuning, antenna, gain) without waiting on SAME decode
or STT.

No `compose.yaml` service or Dockerfile of its own: this project ships
inside `sdr-rx`'s container image (`../sdr_rx/Dockerfile`, build context
the repo root) as one of four independent uv projects/venvs, started by
`../sdr_rx/entrypoint.sh` as a self-restarting background process. Still
fully independent of `sdr-rx` at the Python level (own `pyproject.toml`,
own tests, no cross-import) -- `../sdr_rx/README.md`'s "Container" section
has the full picture.

Icecast over MediaMTX for this v1 -- see `feeder.py`'s docstring for the
tradeoff.

## Status

Implemented and unit tested: mount-name/source-URL building and the ffmpeg
subprocess wrapper (`feeder.py`), the per-(site, channel) streaming
orchestration including lazy feeder creation and not retrying a feeder that
died (`service.py`), and the ZMQ subscriber (`subscriber.py`). ffmpeg and a
real Icecast server aren't available in the authoring sandbox, so
`feeder.py`'s subprocess plumbing is tested against a Python stand-in
rather than real ffmpeg -- see its test file. The full path (ffmpeg
actually encoding to a real Icecast mountpoint, a browser playing it back)
is not yet verified -- see the repo root README's bring-up runbook.

### Buffering

`FFmpegFeeder.write()` (`feeder.py`) never blocks the caller. It pushes PCM
onto a small bounded queue drained by a dedicated writer thread that owns
the actual (blocking) `stdin.write()` to ffmpeg; if that queue fills --
because ffmpeg is itself stalled writing to Icecast over a bad network link
-- the oldest buffered chunk is dropped to make room for the newest. This
matters because `main()`'s loop is single-threaded: `subscriber.recv()` ->
`streamer.feed()` -> `feeder.write()` in lockstep. Before this, a stalled
`write()` stalled that whole loop, which stopped draining the ZMQ SUB
socket, which silently dropped frames once its own receive buffer filled
(`subscriber.py`) -- the actual cause of audible cutouts, not anything
downstream in Icecast. The queue holds ~2s of audio (`feeder.DEFAULT_QUEUE_MAXSIZE`);
long enough to ride out a brief stall without adding much latency to an
already-not-low-latency stream.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `LIVE_AUDIO_ZMQ_CONNECT` | `tcp://localhost:5555` | Address to connect to sdr-rx's ZMQ PUB socket -- `localhost`, since both run in the same container now (see above). |
| `LIVE_AUDIO_CHANNELS` | *(unset -- all channels)* | Comma-separated NWR channel allowlist, e.g. `WX5,WX7`. Gates which channels ever get a feeder (`service.py`'s `Streamer`) -- a channel not in the list never spawns an ffmpeg process or opens an Icecast source connection, rather than streaming silence. Most sites only have usable signal on one or two of the seven channels; the rest otherwise ran a permanent encode/connection for no listener (`docs/design/tracking.md`). SAME decode and the alert ring buffer are sdr-rx's, not this service's, and keep watching every channel regardless -- this only trims the audible feed. `sdr-rx` reads this same variable to skip producing that channel's audio in the first place (`services/sdr_rx/README.md`) -- set it once, in the one container both of these run in. |
| `ICECAST_HOST` | `icecast` | Icecast server hostname. |
| `ICECAST_PORT` | `8000` | Icecast server port. Compose sets this from the top-level `ICECAST_PORT` in `.env`, which also drives Icecast's own listen socket and the published host port -- see the root README's "Ports". |
| `ICECAST_SOURCE_USER` | `source` | Icecast source-client username (Icecast's convention: always `source`). |
| `ICECAST_SOURCE_PASSWORD` | `hackme` | Icecast source-client password. Compose passes the same `.env` value to the `icecast` service too, which renders it into `<source-password>` at container start (`deploy/icecast/entrypoint.sh`) -- the two can't drift out of sync, so there's nothing to hand-edit in `icecast.xml`. |
| `ICECAST_STREAM_NAME_TEMPLATE` | `Tocsin {site} {channel}` | Stream name shown on Icecast's status page and in players. `{site}`/`{channel}` are substituted with the mount's site/channel -- or their display-name overrides, see `LIVE_AUDIO_METADATA_CONFIG` below. |
| `ICECAST_STREAM_DESCRIPTION` | `Tocsin NOAA Weather Radio relay` | Stream description, same for every mount. |
| `ICECAST_STREAM_GENRE` | `weather` | Stream genre, same for every mount. |
| `LIVE_AUDIO_METADATA_CONFIG` | *(none)* | Path to an optional YAML file with `site_names`/`channel_names` display-name overrides used by `ICECAST_STREAM_NAME_TEMPLATE` above, e.g. showing the `home` site from `SDR_RX_DEVICES` as "Portland Home Station" instead of `home`:<br>`site_names:`<br>`  home: Portland Home Station`<br>`channel_names:`<br>`  WX5: Channel 5` |
| `LIVE_AUDIO_REDIS_URL` | *(unset)* | Optional, heartbeat only. When set, publishes liveness to `tocsin:status:live_audio` (with the current mount list) so `api`'s `GET /services` and `GET /streams` can see this process. Audio still goes to Icecast, never through Redis. |

Each active channel appears at `http://<icecast-host>:<ICECAST_PORT>/<site>-<channel>.ogg`
(`8000` unless you changed it).

## Development

```sh
uv sync
uv run pytest
```
