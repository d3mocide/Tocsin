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

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `LIVE_AUDIO_ZMQ_CONNECT` | `tcp://localhost:5555` | Address to connect to sdr-rx's ZMQ PUB socket -- `localhost`, since both run in the same container now (see above). |
| `ICECAST_HOST` | `icecast` | Icecast server hostname. |
| `ICECAST_PORT` | `8000` | Icecast server port. |
| `ICECAST_SOURCE_USER` | `source` | Icecast source-client username (Icecast's convention: always `source`). |
| `ICECAST_SOURCE_PASSWORD` | `hackme` | Must match `<source-password>` in `deploy/icecast/icecast.xml`. |
| `ICECAST_STREAM_NAME_TEMPLATE` | `Tocsin {site} {channel}` | Stream name shown on Icecast's status page and in players. `{site}`/`{channel}` are substituted with the mount's site/channel -- or their display-name overrides, see `LIVE_AUDIO_METADATA_CONFIG` below. |
| `ICECAST_STREAM_DESCRIPTION` | `Tocsin NOAA Weather Radio relay` | Stream description, same for every mount. |
| `ICECAST_STREAM_GENRE` | `weather` | Stream genre, same for every mount. |
| `LIVE_AUDIO_METADATA_CONFIG` | *(none)* | Path to an optional YAML file with `site_names`/`channel_names` display-name overrides used by `ICECAST_STREAM_NAME_TEMPLATE` above, e.g. showing the `home` site from `SDR_RX_DEVICES` as "Portland Home Station" instead of `home`:<br>`site_names:`<br>`  home: Portland Home Station`<br>`channel_names:`<br>`  WX5: Channel 5` |
| `LIVE_AUDIO_REDIS_URL` | *(unset)* | Optional, heartbeat only. When set, publishes liveness to `tocsin:status:live_audio` (with the current mount list) so `api`'s `GET /services` and `GET /streams` can see this process. Audio still goes to Icecast, never through Redis. |

Each active channel appears at `http://<icecast-host>:8000/<site>-<channel>.ogg`.

## Development

```sh
uv sync
uv run pytest
```
