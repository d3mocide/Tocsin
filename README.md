# Tocsin

A dual-path NOAA Weather Radio All Hazards (NWR) alert monitor with mesh egress.

Tocsin receives NWR broadcasts over SDR, decodes EAS/SAME alert headers, transcribes the
voice message, independently polls the NWS CAP API, fuses both sources into a single
provenance-preserving alert feed, and dispatches alerts over Meshtastic and MQTT.

**The system must remain fully functional with no internet connection.** Network-dependent
components add quality, never capability. See `docs/design/master-prompt.md` for the full design
document -- this README summarizes it; the design doc is the source of truth for anything
not covered here. For the phase-by-phase build plan and current status, see
`docs/design/roadmap.md` and `docs/design/tracking.md`.

## Deployment modes

| Mode | Hardware | Network |
|---|---|---|
| `offgrid` | Raspberry Pi 5 (or low-power x86), RTL-SDR, Meshtastic node on serial | None |
| `hybrid` | Same, plus internet | NWS API, remote STT, LiteLLM, MQTT bridge available |

Both modes run from one `compose.yaml` using Docker Compose profiles, selected by a single
`TOCSIN_MODE=offgrid|hybrid` environment variable.

## Hardware bring-up

This is the sequence to go from a cloned repo to a real RTL-SDR dongle feeding decoded SAME
events and a listenable audio stream. Everything up through step 4 works with no dongle
plugged in yet -- only step 5 onward needs hardware. Steps 1-4 have been run for real
against a Docker daemon (see `docs/design/tracking.md`, 2026-08-08) with `/dev/bus/usb`
passthrough stubbed out (this repo's own dev sandbox has no USB subsystem to test that
part against); step 4's `make up-offgrid` came up clean with all non-`sdr-rx` services
staying up and `sdr-rx` exiting 0 as designed.

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
   `export POSTGRES_PASSWORD=...`.
4. **Bring the stack up without a dongle first** to confirm the software side is healthy:
   `make up-offgrid`. `sdr-rx` will report "no devices configured" and exit cleanly (that's
   expected -- see its README); `same-decoder`, `live-audio`, and `icecast` should all stay
   up.
5. **Plug in the dongle**, then find its serial: `make sdr-devices`.
6. **Set `SDR_RX_DEVICES`** to `site:serial` (e.g. `export SDR_RX_DEVICES=home:00000001`)
   and restart: `make down && make up-offgrid`.
7. **Verify the RF path is alive**:
   - Logs: `docker compose logs -f sdr-rx` should show no repeated errors.
   - Listen: open `http://<host>:8000/home-WX5.ogg` (swap in your site/channel; see
     `services/live_audio/README.md`) in a browser or media player -- you should hear NWR's
     continuous broadcast. This is the fastest way to confirm tuning/gain/antenna before
     worrying about SAME decode at all.
   - Decode: `docker compose logs -f same-decoder` -- NWR broadcasts a Required Weekly Test
     (RWT) on a schedule (and RMT monthly); when one airs, you should see a JSON event line
     with `"event_code": "RWT"`. You don't have to wait for a real warning to confirm the
     whole pipeline works end to end.
8. **Tweak from there.** Gain (`sdr_rx.capture.DEFAULT_GAIN_DB`, currently a fixed 30 dB per
   the design doc), which of the seven WX channels you expect to hear locally, and the
   local transmitter frequency assumption (design doc §12 open item) are the things most
   likely to need adjusting against your actual RF environment.

None of steps 5-8 have been verified against real hardware yet in this repo's history --
that's the actual gap this section exists to close. See `docs/design/tracking.md` for
exactly what's confirmed vs. still open.

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
│   ├── dispatcher/              # egress/{meshtastic_serial,meshtastic_mqtt,mqtt}.py
│   └── api/
├── web/
├── data/
│   ├── same_event_codes.yaml    # code → name, tier
│   ├── same_to_cap.yaml         # SAME event code ↔ CAP event name
│   └── fips.csv                 # FIPS → county name, for templating
├── deploy/
│   ├── mosquitto/                # mosquitto.conf
│   ├── icecast/                  # icecast.xml, Dockerfile
│   └── udev/                     # host-side RTL-SDR udev rule
└── docs/
    └── design/
        ├── master-prompt.md     # the original design spec -- source of truth
        ├── roadmap.md           # phase-by-phase build plan
        └── tracking.md          # living status against the roadmap
```

## Build order

Each phase is independently verifiable, and normally you wouldn't start implementing phase
N+1 until phase N is proven on real hardware -- see `docs/design/roadmap.md` and CLAUDE.md.
Phases 1-3 below are an intentional, explicit exception: everything in each that doesn't
require a physical RTL-SDR has been built and unit tested ahead of live-hardware
verification, specifically so that plugging in a dongle is the *last* step instead of the
next thing to build. Phase 1's live-hardware proof is still the real gate before trusting
any of it operationally -- see `docs/design/tracking.md` for exactly what's confirmed vs.
still open, and don't read "implemented" below as "verified."

0. Bootstrap (repo scaffolding, compose profiles, checked-in reference data). **Done.**
1. Channelizer (`services/sdr_rx`). **Done**, including live-hardware verification: a real
   RTL-SDR dongle on a Raspberry Pi 5 locked all seven WX channels.
2. SAME decode end to end (`services/same_decoder`: multimon-ng → parsed, tiered event).
   Implemented, unit tested, build/runtime-verified. **Not yet verified:** an actual decoded
   SAME/EAS header from real RF (real NWR *voice* audio is confirmed flowing, per Phase 1/3;
   no header has aired during testing yet) -- this is the one gap every phase since has
   inherited.
3. Live audio (`services/live_audio` + Icecast). **Done**, including live-hardware
   verification: real RF-sourced audio audible in a browser.
4. Segment capture + local STT (`services/segment_capture` + `services/stt_worker`).
   Implemented and unit tested, including Phase 7's `remote_http` provider and `STT_CHAIN`
   race. Blocked on the same real-SAME-header gap as Phase 2 for live verification.
5. NWS poller + fusion (`services/nws_poller` + `services/fusion`). Implemented and fully
   verified against its own exit criteria (fixture-covered correlation logic needs no
   hardware) -- see `docs/design/tracking.md`.
6. Dispatcher stage 1 (`services/dispatcher`: template message, serial Meshtastic,
   idempotency, rate limiting). Implemented and unit tested.
7. Dispatcher stage 2 + remote STT (LiteLLM enrichment, circuit breaker, Meshtastic MQTT
   fallback). Implemented and unit tested, including both of this phase's literal roadmap
   exit criteria exercised directly in tests.
8. API + web UI (`services/api` + `web/`). Implemented and unit tested: FastAPI REST + SSE
   over a real TimescaleDB-backed alert store (the first thing in this repo to actually
   write to Postgres), RF health + spectrum display, `RF_ONLY`/`API_ONLY` divergence rate.
   `web/`'s TypeScript type-checks and builds cleanly; not run against a real browser/backend
   in this sandbox.

Phases 5-8 were built ahead of Phase 2's real-audio proof, at the user's explicit direction,
to reach a whole-stack MVP faster -- see `docs/design/tracking.md`'s per-phase notes for the
full done/open breakdown and every build-order exception's reasoning. None of them are
verified against real hardware, a real Meshtastic node, a real LiteLLM endpoint, or a real
Postgres/Redis instance; every wire contract with external systems (Meshtastic serial/MQTT,
LiteLLM, the OpenAI STT shape, the NWS CAP API) was checked against real published specs
rather than guessed, which is a meaningfully different claim from "verified live."

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
