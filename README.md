# Tocsin

A dual-path NOAA Weather Radio All Hazards (NWR) alert monitor with mesh egress.

Tocsin receives NWR broadcasts over SDR, decodes EAS/SAME alert headers, transcribes the
voice message, independently polls the NWS CAP API, fuses both sources into a single
provenance-preserving alert feed, and dispatches alerts over Meshtastic.

**The system must remain fully functional with no internet connection.** Network-dependent
components add quality, never capability. See `docs/design/master-prompt.md` for the full design
document -- this README summarizes it; the design doc is the source of truth for anything
not covered here. For the phase-by-phase build plan and current status, see
`docs/design/roadmap.md` and `docs/design/tracking.md`.

## Deployment modes

| Mode | Hardware | Network |
|---|---|---|
| `offgrid` | Raspberry Pi 5 (or low-power x86), RTL-SDR, Meshtastic node on serial or LAN | None |
| `hybrid` | Same, plus internet | NWS API, remote STT, LiteLLM available |

Both modes run from one `compose.yaml` using Docker Compose profiles, selected by a single
`TOCSIN_MODE=offgrid|hybrid` environment variable.

The Meshtastic node is optional in either mode. To run a receive-only station -- SAME
decode, transcription, alert log and web UI, with no radio to relay over -- drop the mesh
overlay from `COMPOSE_FILE` in `.env`:

```sh
COMPOSE_FILE=compose.yaml
```

Dispatcher still runs stage 1 in full and logs what it would have transmitted. See
`services/dispatcher/README.md`'s "Running without a mesh node".

A Meshtastic node reachable over WiFi/Ethernet works instead of a USB one -- set
`MESHTASTIC_TRANSPORT=tcp` and `MESHTASTIC_TCP_HOST`, and drop the same overlay since there
is no device to map. See that README's "Reaching the node over the network".

## Hardware bring-up

This is the sequence to go from a cloned repo to a real RTL-SDR dongle feeding decoded SAME
events and a listenable audio stream. Everything up through step 4 works with no dongle
plugged in yet -- only step 5 onward needs hardware. Steps 1-4 have been run for real
against a live Docker daemon and come up clean; see `docs/design/tracking.md` for the
verification details.

1. **Blacklist the DVB driver on the host** (not the container) -- the kernel's
   `dvb_usb_rtl28xxu` claims the dongle before SoapySDR can open it otherwise:
   ```sh
   echo "blacklist dvb_usb_rtl28xxu" | sudo tee /etc/modprobe.d/blacklist-rtlsdr.conf
   sudo rmmod dvb_usb_rtl28xxu 2>/dev/null || true   # or reboot
   ```
   `sdr-rx` asserts this at startup and fails loudly if the module is still loaded.
2. **Install the udev rule** so the dongle is group-readable without a privileged container:
   ```sh
   sudo cp deploy/udev/60-rtlsdr.rules /etc/udev/rules.d/
   sudo udevadm control --reload-rules && sudo udevadm trigger
   sudo usermod -aG plugdev "$USER"   # log out/in or reboot
   ```
3. **Set `POSTGRES_PASSWORD`** (required by `compose.yaml`, even though nothing writes to
   Postgres yet) and build everything: `cp .env.example .env` and edit it, or
   `export POSTGRES_PASSWORD=...`. `.env.example`'s `COMPOSE_FILE` already lists
   `compose.sdr.yaml`, the overlay that maps the host USB bus into `sdr-rx` -- keep it.
   `make up-offgrid` and `make up-hybrid` add it back if it's missing, since a station with
   no SDR receives nothing; `make dev-stack` is the one command that deliberately runs
   without it (and without the mesh overlay), for a laptop with no hardware attached.
4. **Bring the stack up without a dongle first** to confirm the software side is healthy:
   `make up-offgrid`. This works with nothing plugged in -- `/dev/bus/usb` exists on any
   Linux host with a USB subsystem, dongle or not. If no Meshtastic node is attached yet
   either, set `COMPOSE_FILE=compose.yaml:compose.sdr.yaml` in `.env` for this step --
   Docker will not start `dispatcher` while its `devices:` mapping points at a serial port
   the host doesn't have.
   `sdr-rx` (the container also running `same-decoder`, `live-audio`, and
   `segment-capture` -- see `services/sdr_rx/README.md`'s "Container" section) will log "no
   devices configured" for its own process and stop retrying it, but stays `Up`: the other
   three processes inside it, plus `icecast`, all keep running normally regardless.
5. **Plug in the dongle**, then find its serial: `make sdr-devices`.
6. **Set `SDR_RX_DEVICES`** to `site:serial` (e.g. `export SDR_RX_DEVICES=home:00000001`)
   and restart: `make down && make up-offgrid`.
7. **Verify the RF path is alive**:
   - Logs: `docker compose logs -f sdr-rx` should show no repeated errors. All four of
     sdr-rx/same-decoder/live-audio/segment-capture's log lines are interleaved here now
     (each line is prefixed with its own service name, e.g. `same-decoder: ...`), since
     they're one container.
   - Listen: open `http://<host>:8000/home-WX5.ogg` (swap in your site/channel, and the
     port if you changed `ICECAST_PORT` -- see "Ports" below and
     `services/live_audio/README.md`) in a browser or media player -- you should hear NWR's
     continuous broadcast. This is the fastest way to confirm tuning/gain/antenna before
     worrying about SAME decode at all.
   - Decode: `docker compose logs -f sdr-rx | grep same-decoder` -- NWR broadcasts a
     Required Weekly Test (RWT) on a schedule (and RMT monthly); when one airs, you should
     see a JSON event line with `"event_code": "RWT"`. You don't have to wait for a real
     warning to confirm the whole pipeline works end to end.
8. **Tweak from there.** Gain (`SDR_RX_GAIN_DB` in `.env`, 30 dB by default per the design
   doc -- see `services/sdr_rx/README.md`'s Configuration table) is the one thing most
   likely to need adjusting against your actual RF environment.

Steps 5-8 (plugging in a dongle onward) haven't been verified against real hardware yet in
this repo's history -- see `docs/design/tracking.md` for exactly what's confirmed vs. still
open.

## Ports

Two ports are published to the host, both set in `.env`:

| Env var | Default | What it is |
|---|---|---|
| `TOCSIN_WEB_PORT` | `8080` | The web UI and the API behind it (same origin): `http://<host>:8080/`. |
| `ICECAST_PORT` | `8000` | Icecast, for live audio: `http://<host>:8000/<site>-<channel>.ogg`. |

Change either in `.env` and `make down && make up-offgrid`; nothing else needs editing.

`ICECAST_PORT` is deliberately one knob for three things -- Icecast's own listen socket,
the published host port, and the port `live-audio`/`api` dial inside the compose network --
because the browser builds playback URLs from this page's hostname on that same port. If
Icecast sits behind a reverse proxy on some other address, set `ICECAST_PUBLIC_URL` instead
of trying to split the two halves apart.

The api container's internal bind port (`API_PORT`, default `8000`) is separately
configurable but rarely worth changing: compose maps `TOCSIN_WEB_PORT` onto it, so it never
appears in a URL you type.

## Web UI

`api` serves a Vite/TypeScript single-page app at `/` (`web/`, see its own README) --
two tabs, no client-side routing:

- **Dashboard** -- live Icecast audio players, nearby NWR stations (sorted by distance once
  `TOCSIN_LATITUDE`/`TOCSIN_LONGITUDE` are set), a Leaflet map of active NWS alert zones and
  nearby transmitters (optional NEXRAD radar overlay), the alert feed (both provenance
  sources shown side by side, never merged), the spectrum waterfall, per-channel RF health,
  system health (the `RF_ONLY`/`API_ONLY` divergence rate), and dispatch outcomes.
- **Activity** -- the merged transcript/dispatch log and per-service status. With
  `LIVE_TRANSCRIPTION_ENABLED=true`, a "Show N live" toggle in this panel's header reveals a
  rolling transcript of one channel's ordinary NWR narration, not just SAME-triggered voice
  messages (hidden by default -- continuous transcription produces a row every few seconds
  and would otherwise bury alert activity). A hazard phrase
  (`data/keyword_triggers.yaml`) appearing in that narration without a SAME header raises a
  `TRANSCRIPT_ONLY` alert in the feed. This is a backstop for a missed or garbled decode,
  not a primary path: it never reaches the mesh (see `docs/design/master-prompt.md`'s
  live-transcription addendum to §4/§6).

  If live transcription is enabled but nothing appears, `segment-capture` logs the measured
  audio levels beside the configured VAD threshold every few minutes -- an uncalibrated
  `LIVE_TRANSCRIPTION_RMS_THRESHOLD` set too high is silent rather than noisy, and that line
  is what it's tuned from.

Installable to a phone's home screen (web manifest + iOS touch icon). No CDN, webfont, or
other external asset, same offgrid rule as the rest of the system -- it degrades to a plain
page with no radio to show data for, never to a blank one.

## Exposing Tocsin behind an external reverse proxy

Design doc §9 has always called for "Docker Compose behind Caddy or NPM"; this is what
that means in practice. Everything below is orthogonal to `TOCSIN_MODE` -- it's about
what's reachable from outside your network, not about internet dependency for the alert
path itself (CLAUDE.md's one rule still holds: SAME decode, local STT, and stage-1
dispatch never need any of this).

1. **Pick one or two ports to forward.** The reverse proxy needs `TOCSIN_WEB_PORT` (the web
   UI and API, default `8080`). If it can also forward a second port to this host, forward
   `ICECAST_PORT` too (default `8000`) and set `ICECAST_PUBLIC_URL` to wherever that's
   reachable, e.g. `https://stream.example.com` or `https://example.com:8443` -- this is
   the cheaper path (`services/api/src/api/streams.py`'s docstring on why: direct-to-Icecast
   playback costs the api process nothing per listener).

   If the proxy can only forward a single port/origin to this host -- common with tunnel-style
   proxies that map one hostname to one backend -- set `ICECAST_PUBLIC_URL=/stream` (a
   relative path, not a host) instead. The web UI then builds same-origin playback URLs and
   `api` proxies the audio bytes itself via `GET /stream/<mount>`. This pins one open
   connection per listener for as long as they listen, so prefer the two-port path above
   when the proxy supports it.

2. **Narrow CORS.** `CORS_ALLOWED_ORIGINS` defaults to `*`, fine for localhost/LAN but not
   once the API is reachable from the internet. Set it to your real origin(s), e.g.
   `CORS_ALLOWED_ORIGINS=https://tocsin.example.com`. Same-origin requests (the normal case,
   since `api` serves the built web UI itself) never need this at all -- it only matters for
   a separate app or dev server reading this API cross-origin.

3. **Change the default passwords.** `POSTGRES_PASSWORD`, `ICECAST_SOURCE_PASSWORD`, and
   `ICECAST_ADMIN_PASSWORD` all default to placeholder values (`changeme`/`hackme`) meant
   for a closed LAN. Set real values in `.env` before exposing anything past localhost --
   `ICECAST_SOURCE_PASSWORD`/`ICECAST_ADMIN_PASSWORD` are rendered into Icecast's own config
   at container start, so there's no separate file to hand-edit.

4. **There is no application-level auth yet** (design doc §9 names "reverse proxy + Argon2id
   local backend auth" as the plan; only the reverse-proxy half is scoped here). Every route
   this API serves is unauthenticated read access to alert/health/transcript data. If that
   matters for your deployment, put auth in the reverse proxy itself (Caddy's `basicauth`,
   an OAuth2 forward-auth proxy, etc.) until backend auth exists.

## Troubleshooting

### The web UI won't load at `http://<host>:8080/`

The UI is served by the `api` container, so it is unreachable whenever `api` isn't
running. Check that first:

```sh
docker compose ps api
docker compose logs --tail=20 api
```

`Restarting` there means `api` is failing at startup, and the last lines say why. The two
common ones:

**`Postgres rejected the password for user 'tocsin'`** -- `POSTGRES_PASSWORD` in `.env`
doesn't match what the `timescale-data` volume was initialized with. Postgres reads
`POSTGRES_PASSWORD` **only** when it creates an empty data directory, so changing it in
`.env` after the first `up` has no effect on the stored password and every later start
fails. Either put the original value back in `.env`, or change the stored one to match:

```sh
docker compose exec timescaledb psql -U tocsin -c "ALTER USER tocsin PASSWORD 'the-value-in-your-.env'"
docker compose up -d api
```

`docker compose down -v` also resolves it, by deleting the volume and everything recorded
in it (alert history, transcripts, RF health series).

**`Postgres ... was still unreachable`** -- `timescaledb` itself isn't up.
`docker compose ps timescaledb` and its logs are the next step. `api` waits out a normal
cold start (compose gates it on `timescaledb`'s healthcheck, then retries for 60s beyond
that), so this means something more than slow startup.

### `sdr-rx` can't open a dongle that's plugged in

```
[ERROR] rtlsdr_get_device_usb_strings(0) failed
sdr-rx: site 'PDX' (49435794): rtlsdr_get_index_by_serial(49435794) - -3
sdr-rx: no devices started successfully
```

This reads like a wrong serial in `SDR_RX_DEVICES`, but `-3` here almost always means the
container has no USB bus at all: `compose.sdr.yaml` is missing from `COMPOSE_FILE` in
`.env`. Without it, libusb still *counts* the dongles but cannot open any of them, so every
descriptor read fails and the serial lookup finds nothing to match. Fix it in `.env`:

```sh
COMPOSE_FILE=compose.yaml:compose.sdr.yaml:compose.mesh.yaml
```

`make up-offgrid`, `make up-hybrid`, and `make sdr-devices` all add the overlay themselves,
so the mismatch only bites a bare `docker compose` invocation. Current builds of `sdr-rx`
check for the mapping at startup and say so directly instead of emitting the librtlsdr
errors above.

If the bus *is* mapped and the errors persist, work back through the host prerequisites in
"Hardware bring-up": the `dvb_usb_rtl28xxu` blacklist (step 1) and the udev rule (step 2).

### `stt-worker` says it's waiting for a model file

Expected until you have staged one -- off-grid means model weights are pre-fetched, never
downloaded on first boot. Run `make fetch-models` (needs network), and the worker picks the
file up within ~15s without a restart. Everything except transcription works meanwhile;
SAME decode, the alert log, dispatch, and the web UI are unaffected.

### `sdr-rx` logs `usb_claim_interface error -6` or `[R82XX] PLL not locked!`

These come from librtlsdr during device enumeration and tuning, not from Tocsin. If the
log goes on to `Using format CF32` and `Allocating 15 zero-copy buffers`, the dongle opened
and you can ignore them. If instead `error -6` (device busy) repeats with no successful
open, something else on the host is holding the device -- usually the kernel's DVB driver,
which is what step 1 of Hardware bring-up blacklists.

## Repository layout

```
tocsin/
├── compose.yaml                 # profiles: offgrid, hybrid
├── Makefile                     # fetch-models, bench-channelizer, sdr-devices, up-offgrid, up-hybrid
├── services/
│   ├── sdr_rx/                  # SoapySDR + PFB channelizer
│   ├── same_decoder/            # multimon-ng EAS/SAME decode -> tiered events
│   ├── live_audio/              # feeds sdr-rx's 16kHz stream into Icecast
│   ├── segment_capture/         # ZCZC->EOM ring-buffer capture + tone-boundary detect
│   ├── stt_worker/              # whisper.cpp transcription + hallucination guards
│   ├── nws_poller/
│   ├── fusion/
│   ├── dispatcher/              # egress/meshtastic_node.py
│   └── api/
├── web/
├── data/
│   ├── same_event_codes.yaml    # code → name, tier
│   ├── same_to_cap.yaml         # SAME event code ↔ CAP event name
│   ├── fips.csv                 # FIPS → county name, for templating
│   └── nwr_stations/            # per-state NWR transmitter reference data
├── deploy/
│   ├── icecast/                  # icecast.xml, Dockerfile
│   └── udev/                     # host-side RTL-SDR udev rule
└── docs/
    └── design/
        ├── master-prompt.md     # the original design spec -- source of truth
        ├── roadmap.md           # phase-by-phase build plan
        └── tracking.md          # living status against the roadmap
```

## Status

All eight design-doc milestones (`docs/design/roadmap.md`) have working, unit-tested code
across `services/`. Phases 1, 2, and 3 (`services/sdr_rx`, `services/same_decoder`,
`services/live_audio`) are additionally verified against a real RTL-SDR dongle on a
Raspberry Pi 5: all seven WX channels locked, live audio audible in a browser, and a real
over-the-air NWR Required Weekly Test decoded end to end into the web UI's alert feed. What's
still unverified is downstream of a *Tier A* event specifically -- capture, transcription,
NWS correlation, and mesh dispatch have only ever run against fixtures and synthetic signals,
since the real event decoded so far (a Required Weekly Test) is Tier C and by design never
reaches the mesh (`services/dispatcher`). Nothing here has run against a real Meshtastic
node, LiteLLM endpoint, or Postgres/Redis instance either, though every wire contract with an
external system was checked against its published spec rather than guessed.

`docs/design/tracking.md` is the living, per-phase record of exactly what's confirmed vs.
still open -- read that instead of this section for anything more specific than "does it
build and pass its tests."

## Non-goals

- **Transmitting.** Receive-only. Transmission on 162.400-162.550 MHz without NOAA
  authorization is a federal offense.
- **Replacing a dedicated SAME weather radio.** Tocsin is a monitoring, logging, and relay
  system. A battery-backed SAME receiver remains the correct primary alerting device for
  overnight and power-outage scenarios.
- **Public rebroadcast.** Personal/emergency use. Public-facing services should review
  NOAA's NWR rebroadcast policy.

## Development

Each service under `services/` is an independent Python project (uv-managed). For example:

```sh
cd services/sdr_rx
uv sync
uv run pytest
```

`make test` runs the test suite for every service that has one (`sdr_rx`, `same_decoder`,
`live_audio`, `segment_capture`, `stt_worker`, `nws_poller`, `fusion`, `dispatcher`, `api`)
plus `web`'s type-check-and-build.

See `CLAUDE.md` / `AGENTS.md` for conventions agents (and humans) should follow when
working in this repo.
