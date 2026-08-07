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

## Host prerequisite

`dvb_usb_rtl28xxu` **must be blacklisted on the host**, not in the container, or the kernel
DVB driver claims the RTL-SDR dongle before SoapySDR can open it:

```sh
echo "blacklist dvb_usb_rtl28xxu" | sudo tee /etc/modprobe.d/blacklist-rtl.conf
sudo rmmod dvb_usb_rtl28xxu 2>/dev/null || true
```

`sdr_rx` asserts this at startup and fails loudly if the module is still loaded.

## Repository layout

```
tocsin/
├── compose.yaml                 # profiles: offgrid, hybrid
├── Makefile                     # fetch-models, bench-channelizer, up-offgrid, up-hybrid
├── services/
│   ├── sdr_rx/                  # SoapySDR + PFB channelizer
│   ├── same_decoder/
│   ├── segment_capture/
│   ├── stt_worker/              # providers/{whispercpp,faster_whisper,remote_http}.py
│   ├── nws_poller/
│   ├── fusion/
│   ├── dispatcher/              # egress/{meshtastic_serial,meshtastic_mqtt,mqtt}.py
│   └── api/
├── web/
├── data/
│   ├── same_event_codes.yaml    # code → name, tier
│   ├── same_to_cap.yaml         # SAME event code ↔ CAP event name
│   └── fips.csv                 # FIPS → county name, for templating
└── docs/
    └── design/
        ├── master-prompt.md     # the original design spec -- source of truth
        ├── roadmap.md           # phase-by-phase build plan
        └── tracking.md          # living status against the roadmap
```

## Build order

Each phase is independently verifiable; do not proceed until the prior one is proven. See
`docs/design/roadmap.md` for what each phase actually involves and `docs/design/tracking.md`
for current status -- this list is just the summary:

0. Bootstrap (repo scaffolding, compose profiles, checked-in reference data). **Done.**
1. Channelizer (`services/sdr_rx`). **In progress** -- synthetic-signal unit tests done
   (48-bin odd-stacked polyphase channelizer, DC blocker, FM discriminator, output
   resampling); SoapySDR capture, ZMQ publishing, and live-hardware verification not
   started.
2. SAME decode end to end (channelizer → multimon-ng → parsed structured event).
3. Live audio (Icecast/MediaMTX from the ZMQ stream).
4. Segment capture + local STT (ring buffer, trim, transcribe, hallucination guards).
5. NWS poller + fusion (correlation logic with recorded fixtures from both sources).
6. Dispatcher stage 1 (template only, serial Meshtastic, idempotency, rate limiting).
7. Dispatcher stage 2 + remote STT (enrichment with all guards and breakers).
8. API + web UI.

Phases past the channelizer are scaffolded as empty service directories only; see each
service's `README.md` for status.

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

See `CLAUDE.md` / `AGENTS.md` for conventions agents (and humans) should follow when
working in this repo.
