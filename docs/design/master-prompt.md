# Tocsin — Design Specification (master prompt)
**A dual-path NOAA Weather Radio alert monitor with mesh egress.**

> This document is a build specification, not a tutorial. It states decisions that have
> already been made and the reasoning behind them. Where it says "must," treat it as a
> constraint; where it says "benchmark" or "verify," treat it as an open item to measure
> rather than assume.

> **This is the master prompt for the project.** It is the original, unmodified
> specification the whole build derives from — every architectural decision, parameter,
> and hazard called out elsewhere in this repo traces back to a section here. Hand this
> document to a new agent (human or AI) as the brief for continuing the build; pair it
> with `docs/design/roadmap.md` for the phase breakdown and `docs/design/tracking.md` for
> current status. Don't edit this file to reflect implementation decisions made
> along the way — those belong in the roadmap/tracking docs or in code comments. This file
> only changes if the underlying requirements actually change.

---

## 1. Mission

Tocsin receives NOAA Weather Radio All Hazards (NWR) broadcasts over SDR, decodes EAS/SAME
alert headers, transcribes the voice message, independently polls the NWS CAP API, fuses
both sources into a single provenance-preserving alert feed, and dispatches alerts over
Meshtastic and MQTT.

The design goal that governs every other decision: **the system must remain fully
functional with no internet connection.** Network-dependent components add quality, never
capability.

### Deployment modes

| Mode | Hardware | Network |
|---|---|---|
| `offgrid` | Raspberry Pi 5 (or low-power x86), RTL-SDR, Meshtastic node on serial | None |
| `hybrid` | Same, plus internet | NWS API, remote STT, LiteLLM, MQTT bridge available |

Both modes run from **one compose file** using Docker Compose profiles. Mode is selected by
a single environment variable that gates all four network-dependent components — not by
per-service flags.

---

## 2. Architecture

```
                     ┌─ live-audio ──────────────→ browser / phone
                     │
[dongle A] ─┐        ├─ same-decoder ─┐
[dongle B] ─┴ sdr-rx ┤                │
             (ZMQ)   ├─ segment-capture ─→ stt-worker ─┐
                     │                                  ├→ fusion → dispatcher ─┬→ meshtastic (serial)
                     └─ health/spectrum ────────────────┤                       ├→ meshtastic (MQTT)
                                                        │                       └→ mosquitto
                          nws-poller ───────────────────┘
```

### Services

| Service | Responsibility | Profile |
|---|---|---|
| `sdr-rx` | Owns the USB dongle(s). Channelizes, demodulates, publishes PCM. | both |
| `live-audio` | Icecast or MediaMTX. Encodes a channel for listening. | both |
| `same-decoder` | multimon-ng `-a EAS` → SAME header parser → structured event | both |
| `segment-capture` | On ZCZC, extracts the voice message clip from the ring buffer | both |
| `stt-worker` | Pluggable transcription (see §6) | both |
| `nws-poller` | `api.weather.gov/alerts/active`, ETag-conditional | hybrid |
| `fusion` | Correlation, dedup, canonical alert store, state machine | both |
| `dispatcher` | Severity policy, rate limiting, Meshtastic + MQTT egress | both |
| `mosquitto` | Local MQTT broker | both |
| `redis` | Bus (streams) + idempotency keys + circuit breaker state | both |
| `postgres` (TimescaleDB) | Alert history, transcripts, RF health time-series | both |
| `api` | FastAPI — REST + SSE feed | both |
| `web` | Vite + TypeScript UI | both |

**Core invariant: one process owns the dongle.** RTL devices are exclusive-open. Every
other component subscribes to `sdr-rx` output. This is what makes the decoder, streamer,
and STT worker independently restartable without touching RF.

---

## 3. `sdr-rx` — SoapySDR + numpy channelizer

Implement a custom polyphase filterbank. Do not shell out to `rtl_fm` or RTLSDR-Airband.

### Parameters

The channel grid lands on bin centers by construction:

| Parameter | Value | Rationale |
|---|---|---|
| Tuner LO | 162.4875 MHz | Bin *edge*, not a channel — DC spike falls between WX4 and WX5 |
| Sample rate | 1.2 MS/s | Inside RTL's stable 0.9–3.2 MS/s window; 1.2e6 / 25e3 = 48 exactly |
| Channelizer | 48-bin odd-stacked PFB | Bins at LO + (k+0.5)·25 kHz land dead-center on all seven NWR channels |
| Decimation | D = 24 (2× oversampled) | D = M aliases at channel edges; 2× oversampling gives clean rolloff |
| Output rate | 50 kS/s complex per bin | Comfortable for ±5 kHz deviation NFM discriminator |
| Prototype filter | `firwin`, 576 taps (12/channel), cutoff 1/48 | Standard PFB starting point |
| Gain | Manual, start 30 dB | Auto gain oscillates on a constant carrier |

### Bin mapping

| k | Frequency | Channel |
|---|---|---|
| -4 | 162.400 | WX1 |
| -3 | 162.425 | WX2 |
| -2 | 162.450 | WX3 |
| -1 | 162.475 | WX4 |
| 0 | 162.500 | WX5 |
| 1 | 162.525 | WX6 |
| 2 | 162.550 | WX7 |

All 48 bins are computed (the FFT costs the same either way). The 41 unused bins feed the
spectrum/waterfall display as free occupancy data.

### Three implementation hazards

1. **Odd-stacked PFB with D = M/2 requires a phase correction.** Alternate output frames
   pick up a per-bin rotation; apply a `(-1)^k` multiply on odd frames after the FFT.
   Omitting this produces a channel that works intermittently and drifts — the hardest bug
   in the build to diagnose from symptoms alone. Write a unit test with a synthetic tone
   swept across bin centers that asserts constant output amplitude.
2. **Batch the FFTs.** Do not loop 50,000×/sec. Buffer input, reshape to `(n_frames, 48)`
   after the polyphase arms, single `np.fft.fft(..., axis=1)`. This is the difference
   between ~15% of a core and not keeping up on a Pi.
3. **DC-block before channelizing.** The LO sits on a bin edge, so the RTL DC spike
   straddles WX4/WX5. Single-pole IIR high-pass on the complex stream:
   `y[n] = x[n] - x[n-1] + 0.9995*y[n-1]`.

### Output contract

Post-discriminator resampling, per consumer:

- `resample_poly(x, 441, 1000)` → **22050 Hz** s16le mono → multimon-ng
- `resample_poly(x, 8, 25)` → **16000 Hz** s16le mono → STT and live audio

**Bus:** ZeroMQ PUB over the compose network. Multipart frames: `[topic][json header][pcm]`.
PUB/SUB drops at the high-water mark, which is correct for live audio and wrong for the
decoder — give `same-decoder` a generous HWM.

**Ring buffer:** `sdr-rx` additionally writes a 30-second rolling raw buffer per channel to
tmpfs. `segment-capture` reads from this rather than racing the ZMQ stream, which gives it
pre-roll so the SAME header audio itself is captured for logging.

### Health signal

Silence is indistinguishable from "no alerts" unless you measure it. NWR broadcasts
continuously, so:

- Per-channel audio RMS and channel power, sampled continuously into TimescaleDB
- Flat carrier > 30s ⇒ RF path is **dead**, surfaced loudly in the UI and over MQTT
- This is the primary liveness signal for the entire SDR path

### Multi-dongle

A second dongle covers a second *transmitter site* (different antenna, different
propagation), not additional channels — one dongle already covers all seven. Dongles are
addressed by serial number, never by index. Set serials with `rtl_eeprom` during bring-up.

### Host prerequisite

`dvb_usb_rtl28xxu` **must be blacklisted on the host**, not in the container, or the kernel
DVB driver claims the dongle first. Document this in the README and assert it at startup
with a clear error.

---

## 4. `same-decoder` and `segment-capture`

Pipe the 22050 Hz stream to `multimon-ng -t raw -a EAS -`. Parse `ZCZC` headers into
structured events.

### SAME header fields

`ZCZC-ORG-EEE-PSSCCC-PSSCCC+TTTT-JJJHHMM-LLLLLLLL-`

- `ORG` — originator: `WXR`, `CIV`, `EAS`, `PEP`, `EAN`
- `EEE` — 3-char event code
- `PSSCCC` — 6-digit FIPS, repeatable up to 31 times. `P` is the county subdivision digit.
- `+TTTT` — purge time, offset from issue (not an absolute time)
- `JJJHHMM` — issue time, UTC ordinal day + HH:MM
- `LLLLLLLL` — originating station callsign

Header is transmitted three times; multimon-ng declares valid on two matching copies.
Parser must tolerate a garbled third copy.

### Message structure and capture window

```
[SAME header ×3] → [1050 Hz attention tone, 8–11s] → [voice message] → [NNNN EOM ×3]
```

`segment-capture` starts on ZCZC detect, ends on EOM or a hard timeout (default 300s), and
emits a WAV artifact plus timing metadata marking where the attention tone ends and voice
begins. That boundary is used by §6 to trim before inference.

### Event codes → tiers

Ship as a checked-in YAML, not a dict in code — NWS revises the list periodically.

- **Tier A (mesh + MQTT):** `TOR SVR FFW EWW TSW CEM CDW LEW SPW EQW VOW AVW HMW NUW RHW`
- **Tier B (MQTT only):** watches, advisories, statements
- **Tier C (log only):** `RWT` `RMT` tests, routine programming

### Continuous capture (addendum)

`segment-capture` also, optionally, runs one *second* capture path, independent of the
ZCZC/EOM detector above: a VAD-segmented continuous capture on a single configured
`(site, channel)`, with no SAME header involved at all. See §6's addendum for the full
shape — this exists because everything above only ever transcribes a message that both
happened *and* was successfully SAME-decoded, and NWR carries plenty of voice that is
neither.

---

## 5. `fusion` — correlation and provenance

**Do not hard-merge the two sources.** They cover different sets:

- **SAME/NWR** is county-granular, carries non-weather EAS (civil emergency, AMBER,
  national activation), and is the only source that survives an internet outage.
- **NWS CAP API** is polygon-granular, carries VTEC, gives full alert text, and includes
  products never broadcast on NWR.

### Correlation key

```
(SAME event code ↔ CAP event name)          # via the checked-in mapping YAML
AND (SAME FIPS set ∩ CAP geocode.SAME ≠ ∅)  # CAP payloads from NWS carry geocode.SAME
AND (issue times overlap within tolerance)   # default ±5 min
```

CAP's `parameters.VTEC` gives phenomenon/significance/ETN as a canonical ID on the API
side. SAME carries no ETN, so time-window matching is unavoidable for the RF side.

### Canonical model

One `Alert` with a `sources[]` array — never a merged blob. State:

| State | Meaning |
|---|---|
| `RF_ONLY` | SDR heard it, API hasn't. Emit immediately — NWR typically leads the API by seconds. |
| `API_ONLY` | Transmitter down, out of footprint, or a non-broadcast product. |
| `CONFIRMED` | Both agree. Highest confidence. |
| `TRANSCRIPT_ONLY` | A keyword hit in continuously-transcribed audio (§6 addendum) — no SAME header, no CAP match. |

The `RF_ONLY`/`API_ONLY` divergence rate over time is the best single health metric for the
whole system. `TRANSCRIPT_ONLY` is deliberately excluded from that metric — it's a
fuzzy keyword match in ordinary narration, not a second independent decode of the same
event, so folding it into RF-vs-API agreement would corrupt the one number this system
uses to say "the dual-path architecture is working." It also never attempts CAP
correlation itself: freeform speech carries no reliable county-level geography for
`matches()`'s FIPS-overlap check to run against, so a keyword hit stays its own alert
rather than trying (and reliably failing) to confirm.

### Confidence must be mode-relative

In `hybrid`, `RF_ONLY` means the API lagged or disagreed — mildly interesting. In
`offgrid`, it is the *only possible state*. If confidence is computed absolutely, off-grid
deployments show a permanent warning light on a perfectly healthy system. **Deployment mode
is an input to the confidence calculation.**

`TRANSCRIPT_ONLY` does *not* get `RF_ONLY`'s "only possible state off-grid, so don't warn
about it" treatment, even though it can also be the only signal available off-grid: unlike
`RF_ONLY`'s deterministic SAME header decode, it's a fuzzy phrase match with a real
false-positive rate, so its confidence stays low in both modes — low enough to read as
"worth a look," never "as good as a decoded header."

### Durability

Both paths write raw events to Redis Streams before `fusion` sees them. If `fusion` crashes
mid-event it resumes from the consumer group rather than losing an alert.

---

## 6. `stt-worker` — pluggable transcription

Single worker, uniform input contract: **16 kHz mono s16le WAV**. No provider ever sees a
different format.

### Providers

| Provider | Target |
|---|---|
| `local_whispercpp` | Pi / low-power CPU. ggml quantized models from a mounted volume. |
| `local_faster_whisper` | CUDA. Jetson or any GPU host. |
| `remote_http` | OpenAI-compatible `/v1/audio/transcriptions` |

That one remote endpoint shape covers a self-hosted faster-whisper-server, LiteLLM routing,
or a commercial API with **no code change** between them.

### Selection: race, don't chain

```
STT_CHAIN=local            # offgrid
STT_CHAIN=local,remote     # hybrid
```

In hybrid mode on Tier A events, run local **and** remote in parallel. Local is the floor
and always completes; remote wins if it returns within budget with a better score. This is
the same independent-paths pattern as SDR-vs-API applied one layer down: an internet blip
degrades transcript *quality* rather than producing no transcript. Tier B is local-only.

### Why CPU inference is acceptable here

Stage 1 of dispatch (§7) already fired at T+0 from the SAME header with no STT involved, so
the STT latency budget is soft — 2–3 minutes is fine for an enrichment message. This is the
single design property that makes a Raspberry Pi viable.

Rough shape on a Pi 5, **to be benchmarked rather than trusted**: `tiny.en` faster than
realtime, `base.en` near 1.5–2× realtime, `small.en` too slow if warnings stack. A typical
NWR warning is 30–120s of voice. Suggested defaults: `base.en` off-grid, `small.en`
hybrid-local. Seed `initial_prompt` with local county and place names — NWR's synthesized
voices fail almost exclusively on proper nouns.

Core budget on a 4-core Pi: 1 for the channelizer, 2 for Whisper, 1 for everything else.

### Two preprocessing steps that matter more than model size

1. **Trim before inference.** Strip the SAME header bursts and the 8–11s attention tone
   using the boundary metadata from `segment-capture`. On a Pi this recovers a meaningful
   fraction of inference time.
2. **Guard against hallucination.** Whisper emits confident garbage on tone-heavy and
   near-silent audio, and NWR is full of both. Require `no_speech_prob` and `avg_logprob`
   thresholds plus a blocklist for classic artifacts ("Thank you for watching," subtitle
   credit strings). **An unguarded transcript feeding LiteLLM feeding a mesh broadcast is
   the worst failure chain in this system** — a tone burst becomes a confidently-worded
   warning detail sent to every node on the mesh. Treat this as a correctness requirement,
   not a polish item.

### Continuous transcription and keyword-triggered alerts (addendum)

Everything above transcribes only what `segment-capture` hands it, and `segment-capture`
(§4) only ever starts recording on a decoded `ZCZC` header. That leaves two real gaps: a
listener gets no sense of what NWR is actually saying between alerts, and a product that
never got SAME-encoded — a forecaster ad-lib, or a header `multimon-ng` failed to decode
under poor SNR — produces no transcript and no alert at all, even though the hazard was
genuinely spoken over the air.

**Continuous capture, one channel only.** `segment-capture` optionally runs a second,
independent capture path alongside its ZCZC/EOM detector: a simple energy-based VAD
segmenter that polls the same ring buffer continuously, cutting a WAV chunk on a
silence-hysteresis boundary or a hard max-chunk-duration cap, with no SAME header involved
at all. Deliberately scoped to a single configured `(site, channel)`, never "every channel
with audio" — the CPU budget above (2 of 4 Pi cores for Whisper) assumes occasional,
alert-triggered inference, not continuous inference across all seven NWR channels at once.
Off by default (`LIVE_TRANSCRIPTION_ENABLED`).

**Transcription, local-only, always.** A continuous chunk always transcribes with the
local provider, never races remote — the Tier A race above is for alert enrichment on a
soft latency budget, not ambient narration — and is dropped outright, never sent over the
network, if no local provider is configured at all. Continuous transcription must work
fully off-grid, the same as every other path this document calls core. It still passes
through the same hallucination guard as every other transcript before its text is trusted
for anything, including keyword matching below.

**Keyword matching is a backstop, not a primary path.** A guarded live transcript is
scanned against a checked-in phrase table, `data/keyword_triggers.yaml` (spoken phrase →
SAME event code, resolved to a name/tier via `data/same_event_codes.yaml` — the same tier
table §4 uses, so a keyword match carries identical tier semantics to a decoded header). A
match produces a `fusion` alert in the `TRANSCRIPT_ONLY` state (§5), with its own, lower,
mode-relative confidence: a fuzzy phrase match in a Whisper transcript is never treated as
equivalent to a deterministic SAME header decode.

**Never reaches the mesh.** A `TRANSCRIPT_ONLY` alert has no RF source, so dispatcher's
stage 1 (§7), which fires only off a decoded SAME header, never sees it. Its underlying
transcript record also carries a fixed `LIVE`/Tier C marker regardless of what tier a
keyword match inside it resolves to, so stage 2's Tier A gate excludes it as well. The
worst failure chain named just above — an unguarded transcript reaching the mesh — stays
impossible by construction for this path too; a keyword hit only ever surfaces in the web
UI today (§12 has the open item on a general Tier B/MQTT publish path, which this would
also want once it exists).

---

## 7. `dispatcher` — two-stage emission

### Stage 1 — T+0s, on SAME header decode

Deterministic, ≤140 bytes, **zero dependencies**. Every field comes from the SAME header
itself. No STT, no LLM, no API. This fires before the voice message has finished playing.

```
TOR WARN | Multnomah,Clackamas OR | exp 2145Z | RF
```

Requires an RF source, full stop — a `TRANSCRIPT_ONLY` alert (§5, §6 addendum) has none,
so stage 1 never fires for one no matter its keyword-matched tier. A fuzzy phrase match in
a Whisper transcript must never carry stage 1's "this came straight off a decoded header"
guarantee.

### Stage 2 — T+60–120s, after EOM and STT

Tier A only. LiteLLM compresses the transcript to an impact clause within the remaining
byte budget. ≤200 bytes.

Hard guards, or this will eventually hang the dispatcher:

- 3s LiteLLM timeout
- Circuit breaker after N consecutive failures (state in Redis)
- Output validation: length, ASCII-only, no newlines
- **Any failure ⇒ stage 2 is silently skipped.** Stage 1 already delivered, so a failure
  degrades detail, never delivery.

In `offgrid` mode, stage 2 is template-only or omitted entirely.

### Meshtastic dual path

Serial primary, MQTT fallback, keyed on **acknowledgment** rather than connection state:

```
emit(msg) with idempotency key (event, fips_set, etn, stage)
  → meshtastic-python sendText(wantAck=True) over serial/TCP
  → wait 15s for ack
       ack    → mark delivered, done
       no ack → publish to msh/US/2/json/mqtt/ on gateway node
  → mark delivered; key persists in Redis across restarts
```

The persisted idempotency key is what stops a dispatcher restart from re-flooding the mesh
with alerts it already sent. It must survive the container, not just the process.

MQTT leg caveats: requires `json_enabled` on the gateway node, works only on the primary
channel with a known PSK, and needs an internet-connected node. It is a hedge against a
dead USB cable, **not** against a grid event — the serial path is the one that matters.

### Airtime budget

Meshtastic text payload ceiling is ~237 bytes. Beyond per-message size:

- Token bucket: ~6 msgs/hour sustained, burst 3
- Dedup on `(event, fips, etn)`
- Tier gating per §4

Without this, one active convective evening saturates the mesh for every user on it.

---

## 8. Connectivity contract

Four components need the network. `offgrid` disables all four and the system stays fully
functional:

| Component | Off-grid behavior |
|---|---|
| `nws-poller` | Disabled. Feed becomes RF-only. |
| `stt-worker` remote provider | Local provider only. |
| LiteLLM stage-2 enrichment | Disabled. Template-only mesh messages. |
| Meshtastic MQTT fallback | Disabled. Serial only. |

Driven by **one** env var (`TOCSIN_MODE=offgrid|hybrid`), not per-service flags.

### Model artifacts

Weights live in a mounted volume, never baked into the image. Off-grid means
**pre-staged** — there is no download-on-first-boot.

- `make fetch-models` target, run while a network is still available
- Startup assertion that fails loudly if the configured model is absent

Discovering a missing model at 2 a.m. during an actual event is the scenario this guards
against.

---

## 9. Stack conventions

- **Backend:** FastAPI, async, `arq` for workers
- **Frontend:** Vite + TypeScript
- **Data:** TimescaleDB (alerts, transcripts, RF health series), Redis (bus, idempotency,
  breaker state)
- **Deploy:** Docker Compose behind Caddy or NPM
- **Auth:** reverse proxy + Argon2id local backend auth
- **Agent control files:** maintain `CLAUDE.md` and `AGENTS.md` at repo root

### Suggested layout

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
```

---

## 10. Build order

Each milestone is independently verifiable. Do not proceed until the prior one is proven.

1. **Channelizer standalone.** Synthetic-signal unit tests first (swept tone across bin
   centers, constant amplitude assertion — catches the `(-1)^k` bug). Then live capture,
   confirm all seven bins, confirm CPU headroom on target hardware.
2. **SAME decode end to end.** Channelizer → multimon-ng → parsed structured event. Verify
   against recorded RWT weekly tests before waiting on a real warning.
3. **Live audio.** Icecast/MediaMTX from the ZMQ stream.
4. **Segment capture + local STT.** Ring buffer, trim, transcribe, hallucination guards.
5. **NWS poller + fusion.** Correlation logic with recorded fixtures from both sources.
6. **Dispatcher stage 1.** Template only, serial Meshtastic, idempotency, rate limiting.
7. **Dispatcher stage 2 + remote STT.** Enrichment with all guards and breakers.
8. **API + web UI.**

---

## 11. Non-goals

- **Transmitting.** Receive-only. Transmission on 162.400–162.550 MHz without NOAA
  authorization is a federal offense.
- **Replacing a dedicated SAME weather radio.** Tocsin is a monitoring, logging, and
  relay system. A battery-backed SAME receiver remains the correct primary alerting device
  for overnight and power-outage scenarios. Say so in the README.
- **Public rebroadcast.** Personal/emergency use. Public-facing services should review
  NOAA's NWR rebroadcast policy.

---

## 12. Open items to resolve during build

- Benchmark actual Whisper RTF on the target Pi; confirm the `base.en`/`small.en` defaults.
- Verify local transmitter frequencies against the live waterfall before hardcoding.
  Expected for the Portland WFO area: KIG98 on 162.550, KEC91 (Naselle Ridge) on 162.400 —
  confirm empirically.
- Decide Icecast vs MediaMTX for live audio (latency vs simplicity; MediaMTX gives
  sub-second WebRTC, Icecast is ~5–10s but trivial).
- Evaluate NWWS-OI (XMPP push) as a lower-latency third source alongside API polling in
  hybrid mode.
- Confirm the `same_to_cap.yaml` mapping against the current NWS event code list.
- Calibrate the live-transcription VAD's RMS threshold against a real discriminator feed on
  target hardware (§6 addendum) — the current default is a starting point, not a measured
  value, the same posture as the Whisper RTF benchmark above.
- Build a general Tier B "MQTT only" alert publish path (§4's tiering table has named this
  since the design doc's first draft, but no code implements it yet — the mesh/MQTT dual
  path in §7 is Meshtastic's own ack-fallback bridge, not this). The live-transcription
  addendum's `TRANSCRIPT_ONLY` alerts would use it once it exists; today they're UI-only.
