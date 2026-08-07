# Roadmap

Phase breakdown of `docs/design/master-prompt.md` §10's build order. Each phase is
independently verifiable and gates the next — don't start a phase's implementation on the
assumption that the previous one works; prove it first (unit tests for signal-processing
stages, recorded fixtures for decode/correlation logic, documented verification on target
hardware for anything that needs real RF).

For current status against this roadmap, see `docs/design/tracking.md`. This document
describes the *plan*; that one describes *where we actually are*.

---

## Phase 0 — Bootstrap

**Goal:** repository scaffolding that every later phase builds on.

- Top-level layout, `compose.yaml` (offgrid/hybrid profiles), `Makefile`.
- Checked-in reference data: `data/same_event_codes.yaml`, `data/same_to_cap.yaml`,
  `data/fips.csv`.
- Agent-facing docs: `CLAUDE.md`, `AGENTS.md`, this roadmap and its tracking doc.

**Exit criteria:** `docker compose config` resolves cleanly for both profiles; every
service directory exists with a status README.

**Depends on:** nothing.

---

## Phase 1 — Channelizer (design-doc milestone 1)

**Goal:** turn the raw 1.2 MS/s SDR stream into 48 correctly-behaved complex baseband
channels, proven in isolation before any RF hardware is trusted.

- 48-bin odd-stacked polyphase filterbank (`services/sdr_rx`), DC blocker, batched FFT.
- The three implementation hazards in the master prompt §3 (odd-stacking phase
  correction, batched FFTs, DC blocking) are correctness requirements for this phase, not
  later cleanup.
- Synthetic-signal unit tests: swept tone across all bin centers, constant-amplitude and
  phase-stability assertions.
- SoapySDR device capture loop, tmpfs ring buffer, ZMQ PUB publishing of the two output
  contracts (22050 Hz for `same_decoder`, 16000 Hz for `stt_worker`/live audio).
- Live capture on target hardware: confirm all seven NWR bins lock correctly, confirm CPU
  headroom (`make bench-channelizer`) on a Pi 5.

**Exit criteria:** unit tests green; on real hardware, all seven WX channels demodulate
audibly and the health RMS signal (master prompt §3) shows a live carrier, not silence.

**Depends on:** Phase 0. RTL-SDR hardware for the live-capture half.

**Status:** synthetic-test half done; live-capture half not started (see
`docs/design/tracking.md`).

---

## Phase 2 — SAME decode end to end (milestone 2)

**Goal:** turn channelizer audio into structured SAME/EAS events.

- `same_decoder`: pipe the 22050 Hz stream to `multimon-ng -t raw -a EAS -`.
- Parse `ZCZC` headers (master prompt §4) into structured events; tolerate a garbled third
  header copy.
- Tier lookup via `data/same_event_codes.yaml`.

**Exit criteria:** verified against recorded RWT weekly test captures before waiting on a
real warning to test against.

**Depends on:** Phase 1 (needs real, correctly-demodulated audio to decode).

---

## Phase 3 — Live audio (milestone 3)

**Goal:** a human can listen to a channel in a browser.

- Icecast or MediaMTX fed from the ZMQ 16 kHz stream (master prompt §12 open item: decide
  which — latency vs. simplicity tradeoff).

**Exit criteria:** audio is audible in a browser with acceptable latency for the chosen
tool.

**Depends on:** Phase 1.

---

## Phase 4 — Segment capture + local STT (milestone 4)

**Goal:** turn a SAME-flagged voice message into a guarded transcript.

- `segment_capture`: start on ZCZC, end on EOM or timeout, read from the tmpfs ring buffer
  (not the ZMQ stream) so the SAME header audio itself is captured with pre-roll.
- `stt_worker`: uniform 16 kHz mono s16le input contract, `local_whispercpp` /
  `local_faster_whisper` / `remote_http` providers, `STT_CHAIN` race-don't-chain selection.
- Both preprocessing steps from master prompt §6: trim the attention tone before
  inference, and hallucination guards (`no_speech_prob`, `avg_logprob`, blocklist). The
  guards are a correctness requirement — an unguarded transcript feeding a mesh broadcast
  is called out explicitly as the worst failure chain in the system.

**Exit criteria:** a recorded RWT/RMT capture transcribes correctly (or produces no output,
never confident garbage) end to end, offgrid, on target hardware; benchmark actual Whisper
RTF against the `base.en`/`small.en` defaults (master prompt §12 open item).

**Depends on:** Phase 2 (needs the ring buffer boundary metadata from `segment_capture`,
which depends on SAME detection).

---

## Phase 5 — NWS poller + fusion (milestone 5)

**Goal:** correlate RF-heard events with the NWS CAP feed without hard-merging them.

- `nws_poller` (hybrid only): ETag-conditional polling of `api.weather.gov/alerts/active`.
- `fusion`: correlation key from master prompt §5 (event-code mapping AND FIPS overlap AND
  time-window match), canonical `Alert` model with `sources[]` and
  `RF_ONLY`/`API_ONLY`/`CONFIRMED` state, mode-relative confidence, Redis Streams
  durability.

**Exit criteria:** correlation logic verified against recorded fixtures from both sources
(not live traffic) covering true matches, near-misses (right event wrong county), and
each unmatched state.

**Depends on:** Phase 2 (RF-side events) for full testing; can be developed against
fixtures without it.

---

## Phase 6 — Dispatcher stage 1 (milestone 6)

**Goal:** deterministic, dependency-free alerting the moment a SAME header decodes.

- Template-only stage-1 message (master prompt §7), ≤140 bytes, zero dependencies.
- Serial Meshtastic primary path with `wantAck`, Redis-persisted idempotency key
  (survives container restarts), token-bucket + dedup rate limiting.

**Exit criteria:** a decoded SAME event reaches a real Meshtastic node over serial within
the same session it was decoded in, and a dispatcher restart does not re-send it.

**Depends on:** Phase 2.

---

## Phase 7 — Dispatcher stage 2 + remote STT (milestone 7)

**Goal:** enrich Tier A alerts with an LLM-compressed impact clause, without ever blocking
stage 1.

- LiteLLM enrichment within the remaining byte budget (≤200 bytes), 3s timeout, circuit
  breaker in Redis, output validation (length/ASCII/no-newlines), silent skip on any
  failure.
- Meshtastic MQTT fallback path, keyed on ack rather than connection state.
- `remote_http` STT provider wired into the `STT_CHAIN` race for hybrid mode.

**Exit criteria:** killing the LiteLLM endpoint mid-run degrades stage 2 silently with
stage 1 still delivered; circuit breaker opens after N consecutive failures and recovers.

**Depends on:** Phase 4 (transcript), Phase 6 (stage 1 must exist first).

---

## Phase 8 — API + web UI (milestone 8)

**Goal:** a human-usable view of the fused alert feed and system health.

- FastAPI REST + SSE feed over the canonical alert store.
- Vite + TypeScript UI: alert feed, RF health/spectrum display (the 41 spectrum-only bins
  from Phase 1 feed this), `RF_ONLY`/`API_ONLY` divergence rate as the system health
  metric (master prompt §5).

**Exit criteria:** a browser shows live alerts and RF health without needing to read logs.

**Depends on:** Phase 5 (alert store), Phase 1 (health signal).

---

## Open items carried by the whole roadmap

These aren't a phase; they're standing verification items from master prompt §12 that get
resolved opportunistically as the relevant phase is built, not deferred to the end:

- Confirm local transmitter frequencies against the live waterfall (Phase 1).
- Icecast vs. MediaMTX decision (Phase 3).
- Evaluate NWWS-OI as a lower-latency third source (Phase 5, hybrid mode only).
- Confirm `data/same_to_cap.yaml` against the current NWS event code list (Phase 5, and
  periodically after — NWS revises this list).
