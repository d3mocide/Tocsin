# Implementation Tracking

Living status document for `docs/design/roadmap.md`. Update this whenever a phase's status
changes — this is the thing to read to answer "where are we," not git log archaeology.

**When updating:** change the status/date in the table, add a dated bullet under that
phase's "Notes" with what changed and why, and append a one-line entry to the Session Log
at the bottom. Don't rewrite history in the Session Log — append only.

Status values: `Not Started` · `In Progress` · `Blocked` · `Done`.

---

## Status at a glance

| Phase | Description | Status | Last updated |
|---|---|---|---|
| 0 | Bootstrap | Done | 2026-08-07 |
| 1 | Channelizer | In Progress | 2026-08-07 |
| 2 | SAME decode end to end | Not Started | — |
| 3 | Live audio | Not Started | — |
| 4 | Segment capture + local STT | Not Started | — |
| 5 | NWS poller + fusion | Not Started | — |
| 6 | Dispatcher stage 1 | Not Started | — |
| 7 | Dispatcher stage 2 + remote STT | Not Started | — |
| 8 | API + web UI | Not Started | — |

---

## Phase 0 — Bootstrap

**Status:** Done (2026-08-07)

Repo layout, `compose.yaml` (offgrid/hybrid profiles, validated with
`docker compose config` — a real daemon was not available to validate `up`), `Makefile`,
`data/*.yaml`/`data/fips.csv` (fips.csv seeded for the Portland WFO area only — see
`data/README.md`), `CLAUDE.md`/`AGENTS.md`, this roadmap/tracking pair.

---

## Phase 1 — Channelizer

**Status:** In Progress (2026-08-07)

**Done:**
- `services/sdr_rx`: 48-bin odd-stacked, 2x-oversampled polyphase channelizer, DC blocker,
  FM discriminator, output resampling (22050 Hz / 16000 Hz contracts). 35 unit tests
  passing, including the swept-tone amplitude test and a dedicated phase-stability test
  for the `(-1)^k` odd-frame hazard (master prompt §3) — see `channelizer.py`'s docstring
  for how both were derived and verified empirically.
- `bench_channelizer.py` / `make bench-channelizer` throughput benchmark (not yet run on
  target Pi hardware — only on the dev sandbox).
- `services/sdr_rx/Dockerfile` written but **not build-verified** (no Docker daemon in the
  authoring sandbox).

**Not started:**
- SoapySDR device capture loop.
- ZMQ PUB publishing of the two output streams.
- tmpfs 30s rolling ring buffer per channel.
- Health signal: per-channel RMS/power into TimescaleDB, flat-carrier detection.
- Multi-dongle serial addressing.
- Host-prerequisite assertion (`dvb_usb_rtl28xxu` blacklist check) at startup.
- Live-hardware verification: all seven WX channels, CPU headroom on a Pi 5, local
  transmitter frequency confirmation (master prompt §12).

**Blocked on:** RTL-SDR hardware access for everything in "not started" above except the
ZMQ/ring-buffer plumbing, which is unblocked but not yet written.

---

## Phase 2 — SAME decode end to end

**Status:** Not Started

---

## Phase 3 — Live audio

**Status:** Not Started

---

## Phase 4 — Segment capture + local STT

**Status:** Not Started

---

## Phase 5 — NWS poller + fusion

**Status:** Not Started

---

## Phase 6 — Dispatcher stage 1

**Status:** Not Started

---

## Phase 7 — Dispatcher stage 2 + remote STT

**Status:** Not Started

---

## Phase 8 — API + web UI

**Status:** Not Started

---

## Session Log

- **2026-08-07** — Initial bootstrap. Repo was empty (no commits, no branches). Scaffolded
  Phase 0 in full. Implemented and tested the synthetic-signal half of Phase 1
  (`services/sdr_rx` channelizer + supporting DSP modules); the SoapySDR/ZMQ/hardware half
  of Phase 1 remains open. Added this roadmap/tracking pair plus `docs/design/master-prompt.md`
  (moved from `docs/design/master-prompt.md`, content unchanged) at the user's request to keep the
  original spec, phase plan, and live status as separate, purpose-built documents.
