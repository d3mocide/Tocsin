# Implementation Tracking

Living status document for `docs/design/roadmap.md`. Update this whenever a phase's status
changes — this is the thing to read to answer "where are we," not git log archaeology.

**When updating:** change the status/date in the table, add a dated bullet under that
phase's "Notes" with what changed and why, and append a one-line entry to the Session Log
at the bottom. Don't rewrite history in the Session Log — append only.

Status values: `Not Started` · `In Progress` · `Blocked` · `Done`.

**Note on build order (2026-08-07):** Phases 2 and 3 were built ahead of Phase 1's
live-hardware proof, at the user's explicit request, so that plugging in an RTL-SDR dongle
is the last step rather than the next thing to build. This is a deliberate exception to the
normal "prove phase N before starting N+1" rule (CLAUDE.md, roadmap.md) — everything built
early is the part of each phase that doesn't need real RF (unit-testable DSP/parsing/
plumbing), never the live-hardware verification itself. Treat "In Progress" on phases 2-3
below as "code implemented and unit tested, not yet run against real audio," not as partial
completion of the phase's actual exit criteria.

---

## Status at a glance

| Phase | Description | Status | Last updated |
|---|---|---|---|
| 0 | Bootstrap | Done | 2026-08-07 |
| 1 | Channelizer | In Progress | 2026-08-07 |
| 2 | SAME decode end to end | In Progress | 2026-08-07 |
| 3 | Live audio | In Progress | 2026-08-07 |
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
  FM discriminator, output resampling (22050 Hz / 16000 Hz contracts). Swept-tone amplitude
  test and a dedicated phase-stability test for the `(-1)^k` odd-frame hazard (master
  prompt §3) — see `channelizer.py`'s docstring for how both were derived and verified
  empirically.
- `bench_channelizer.py` / `make bench-channelizer` throughput benchmark (not yet run on
  target Pi hardware — only on the dev sandbox).
- ZMQ PUB publishing (`bus.py`): single PUB socket, `[topic][json header][pcm]` multipart
  frames, `same.<channel>` / `stt.<channel>` topics, generous default HWM per the design
  doc's decoder-vs-live-audio tradeoff. Unit tested over `inproc://`.
- tmpfs 30s rolling ring buffer per channel (`ring_buffer.py`): memmap-backed circular
  buffer of raw (unresampled, `BIN_RATE_HZ`) discriminator output, with a small JSON
  sidecar (`write_pos`/`total_written`) so a reader process (`segment-capture`, milestone
  4) can find pre-roll without racing the writer. Unit tested, including wraparound across
  multiple writes.
- Health signal (`health.py`): per-channel RMS/power, flat-carrier(>30s) dead detection,
  behind a `HealthSink` seam — a `LoggingHealthSink` stands in for the TimescaleDB writer,
  since no service in this repo writes to Postgres yet and standing up that schema isn't a
  Phase-1 dependency. Swapping in a real writer later doesn't touch this module.
- Host-prerequisite assertion (`prerequisites.py`): checks `/proc/modules` for
  `dvb_usb_rtl28xxu` at startup and refuses to start with a clear blacklist/rmmod message
  if it's loaded; a missing `/proc/modules` (non-Linux dev machine) is treated as
  "can't check," not a failure.
- Multi-dongle serial addressing (`capture.py`): `parse_device_config("site:serial,...")`
  parses the `SDR_RX_DEVICES` env var into per-site `DeviceConfig`s (never by index, per
  master prompt §3); `main()` starts one `DevicePipeline` thread per configured device.
- `SoapySDRDevice` (`capture.py`) written against the SoapySDR Python API, lazily imported
  so nothing else in the package needs it installed to be tested. Everything upstream of
  actual device I/O (`DevicePipeline` in `pipeline.py`: DC block → channelize → per-channel
  discriminate → ring-buffer write + ZMQ publish + health sample) is exercised in tests via
  a fake sample source, so the whole path except real hardware I/O is proven without RF.
- `services/sdr_rx` entrypoint (`__init__.py`) now does real work: runs the host check,
  parses `SDR_RX_DEVICES`, and either starts a capture thread per device or reports why it
  can't (no devices configured / SoapySDR bindings missing) and exits cleanly — verified by
  hand for both the no-devices and bad-serial cases.
- `compose.yaml`'s `sdr-rx` service wired with the new env vars and a `tmpfs` mount for the
  ring buffer directory.
- SoapySDR-capable Dockerfile: switched base image from `python:3.11-slim` to
  `debian:bookworm-slim` and install `python3-soapysdr` / `soapysdr-module-rtlsdr` /
  `soapysdr-tools` via apt, with `uv venv --system-site-packages` so the project venv can
  see the apt-installed bindings — see the Dockerfile's own comment for why the base-image
  switch matters (ABI mismatch risk between apt's python3-soapysdr and a separately-built
  interpreter).
- Device enumeration (`capture.enumerate_devices()`, `SDR_RX_LIST_DEVICES=1`) so a dongle's
  serial can be discovered instead of guessed; `make sdr-devices` wraps it.
- `/dev/bus/usb` passthrough added to `compose.yaml`'s `sdr-rx` service; device selection
  stays in the app layer (`SDR_RX_DEVICES`) rather than binding one bus-relative device
  path, since those aren't stable across replugs.
- `deploy/udev/60-rtlsdr.rules`: host-side udev rule (checked-in, not applied
  automatically — see the repo root README's bring-up runbook) granting `plugdev`
  read/write on the standard Realtek RTL2832U vendor/product IDs.
- **Build- and runtime-verified (2026-08-08):** a Docker daemon became available mid-session
  (unavailable when the above was first written) — used it to actually build and run every
  image rather than leave the above as an untested guess. Confirmed: `docker build` succeeds
  for `sdr-rx` on the `debian:bookworm-slim` base; critically, `import SoapySDR` genuinely
  resolves inside the `uv venv --system-site-packages` venv (`SoapySDR.Device.enumerate()`
  runs and returns cleanly with no hardware attached) — the ABI-mismatch risk called out in
  the Dockerfile's comment did not materialize. `SoapySDRUtil --info` confirms the
  `librtlsdrSupport.so` module loads. Ran the full 7-service stack via `docker compose up`
  (with `/dev/bus/usb` passthrough stubbed out, since this sandbox has no USB subsystem at
  all — that one piece is still genuinely hardware-environment-dependent); `sdr-rx` reported
  "no devices configured" and exited 0 exactly as designed. Found and fixed one real bug
  this surfaced: `restart: unless-stopped` was crash-looping `sdr-rx` on that clean exit;
  changed to `restart: on-failure`, which correctly leaves it stopped on exit 0 and only
  retries the exit-1 (device error) path. (Docker/pip/curl in this sandbox route through a
  local TLS-intercepting proxy that build containers don't trust by default — worked around
  *locally, for testing only* by injecting the sandbox's CA bundle into scratch Dockerfile
  copies; nothing about that workaround is in the committed Dockerfiles, since it's a
  sandbox artifact that doesn't exist on a real machine with normal internet access.)

**Not started:**
- Live-hardware verification: all seven WX channels lock on a real dongle, CPU headroom on
  a Pi 5, local transmitter frequency confirmation, host-prerequisite check exercised
  against a real blacklist/rmmod cycle, and `/dev/bus/usb` passthrough on a machine that
  actually has a USB subsystem (master prompt §12).

**Blocked on:** RTL-SDR hardware access for everything in "not started" above — that's now
the *only* thing blocking Phase 1, and it's the only thing that was never testable in this
sandbox regardless of Docker daemon access. Everything not requiring hardware is implemented,
unit tested (71 tests passing across `services/sdr_rx`), and now build/runtime verified too.

---

## Phase 2 — SAME decode end to end

**Status:** In Progress (2026-08-07) — see the build-order note above; this is "implemented
and unit tested," not "verified against real audio."

**Done:**
- `services/same_decoder`, a new uv-managed service (mirrors `sdr_rx`'s src layout):
  - `parser.py`: `ZCZC-...` regex parser per master prompt §4 (originator, event code,
    repeatable FIPS list, purge offset, issue time, callsign). Uses `.search()` rather than
    `.match()`/`.fullmatch()` so a decoder-added prefix (multimon-ng's own `EAS: `) and
    trailing noise don't need special-casing; a line that doesn't contain a well-formed
    header parses to `None` rather than raising. Unit tested against real-format example
    headers (found via web search against public multimon-ng EAS output examples, plus a
    master-prompt-derived example) covering multi-FIPS, single-FIPS, decoder prefixes,
    trailing garbage, and unparseable garbling.
  - `tiers.py`: loads `data/same_event_codes.yaml` (shared, not duplicated — CLAUDE.md);
    unknown event codes fall back to Tier B with a visible placeholder name rather than
    raising or silently dropping, on the reasoning that an unrecognized code more likely
    means the checked-in list needs a refresh (data/README.md's existing "confirm against
    current NWS list" item) than that the message should be ignored.
  - `dedup.py`: TTL-based (default 60s) dedup keyed on parsed header fields rather than the
    raw string, so the header's repeated transmissions collapse to one event.
  - `multimon.py`: subprocess wrapper around `multimon-ng -t raw -a EAS -` with an
    injectable command, a background thread draining stdout into a queue (so write/poll
    don't need to lock-step against multimon-ng's internal buffering), and clean
    terminate/kill-on-timeout shutdown. Tested against a small Python stand-in script, not
    real multimon-ng (not installed in this sandbox) — the plumbing itself (Popen wiring,
    threaded drain, close behavior) is genuinely exercised, just not multimon-ng's actual
    decode.
  - `subscriber.py`: ZMQ SUB client for sdr-rx's `same.<site>.<channel>` topic. Deliberately
    not a shared import from `sdr_rx` (service boundary, CLAUDE.md) — duplicates the small
    amount of wire-format knowledge instead.
  - `service.py`: `Decoder` wires one `multimon.py` subprocess + dedup window per
    `(site, channel)`, created lazily; emits `SameEvent` (event code, name, tier, FIPS
    list, originator, callsign, purge minutes) through an `EventSink` seam — a
    `LoggingEventSink` (JSON line to stdout) stands in until Phase 5 gives it somewhere
    real (Redis Streams / fusion) to go.
  - `__init__.py` `main()`: env-configured (`SAME_DECODER_ZMQ_CONNECT`, `TOCSIN_DATA_DIR`),
    loops on the subscriber and feeds `Decoder`.
  - Dockerfile: `python:3.11-slim` + apt `multimon-ng` + uv — no ABI concern here since
    multimon-ng is a standalone binary, not a Python extension, unlike sdr-rx's SoapySDR
    situation.
  - `compose.yaml`: `same-decoder` service wired up (uncommented), `data/` mounted
    read-only at `/app/data`, depends on `sdr-rx`.
- **Build- and runtime-verified (2026-08-08):** `docker build` succeeds; `multimon-ng
  --help`'s demodulator list confirms `EAS` is a real, available mode (`-a EAS` will work).
  Found and fixed one real bug this surfaced, and it was a bad one: `tiers.py`'s
  `DEFAULT_DATA_DIR = Path(__file__).resolve().parents[4] / "data"` was a *module-level*
  constant, evaluated unconditionally at import time. That math is only valid in a full
  source checkout; inside the Docker image the copied tree is flattened to
  `/app/src/same_decoder/tiers.py` with nothing 4 parents up, so it raised `IndexError` on
  every single import — crash-looping the container in `docker compose up` regardless of
  `TOCSIN_DATA_DIR` being set correctly in `compose.yaml`, because `load()` never even got
  a chance to check the env var before the module-level line already blew up. Fixed by
  making it a lazy function (`_default_data_dir()`, called only from inside `load()` when no
  `data_dir` is passed) with a clear `RuntimeError` instead of a bare `IndexError` if it's
  ever actually called somewhere too shallow. Verified against the real container after the
  fix: `same-decoder` came up and stayed up in `docker compose ps` instead of restarting.
  Added a regression test (`test_default_data_dir_raises_clearly_when_tree_is_too_shallow`)
  — 28 tests passing now, up from 26.

**Not started / open:**
- Verification against real multimon-ng output — the design doc's claim that "multimon-ng
  declares valid on two matching copies" (i.e. majority-voting happens inside multimon-ng
  before it ever prints a line) is taken on faith from the design doc, not confirmed
  against multimon-ng's source. If that assumption is wrong, `dedup.py`'s simpler "collapse
  exact repeats" model may need to become an actual 2-of-3 vote across divergent copies.
- Verification against a recorded RWT/RMT capture, or real SAME audio at all (roadmap
  Phase 2 exit criteria) — multimon-ng itself is confirmed installed and its EAS mode is
  available, but nothing has actually been decoded by it in this sandbox (no RF, no
  recording available). Once hardware is live, NWR's own periodic weekly test is the
  natural first real-world check (see repo root README bring-up runbook step 7).

---

## Phase 3 — Live audio

**Status:** In Progress (2026-08-07) — see the build-order note above.

**Done:**
- Resolved the design doc's open item: **Icecast**, not MediaMTX — the design doc calls
  Icecast "trivial" against MediaMTX's lower-latency-but-more-moving-parts WebRTC path, and
  for a v1 hardware bring-up/tuning tool, "works today" beat "sub-second latency." Revisit
  if the ~5-10s Icecast delay turns out to matter for tuning by ear.
- `deploy/icecast/`: `icecast.xml` (same posture as `deploy/mosquitto/mosquitto.conf` —
  personal/emergency use, default `hackme` password, not meant to be exposed past
  localhost as shipped) and a `Dockerfile` built from `debian:bookworm-slim` + apt
  `icecast2` — no official Icecast Docker image exists, so building our own from apt was
  more defensible than depending on an unverified third-party image.
- `services/live_audio`, a new uv-managed service:
  - `subscriber.py`: ZMQ SUB for sdr-rx's `stt.<site>.<channel>` topic (16 kHz), with a
    smaller default `rcvhwm` than same-decoder's subscriber — dropping under load is
    *correct* here per the design doc's stated tradeoff, the opposite of same-decoder's
    generous-HWM requirement.
  - `feeder.py`: `mount_name`/`icecast_source_url` builders plus `FFmpegFeeder`, a
    subprocess wrapper piping raw PCM to ffmpeg for Ogg/Vorbis-over-Icecast encoding
    (injectable command; tested against a Python stand-in, not real ffmpeg).
  - `service.py`: `Streamer` creates one `FFmpegFeeder` per `(site, channel)` lazily, and
    stops feeding (without crashing the process) if that channel's ffmpeg exits on its own
    — one bad mountpoint shouldn't take every channel down.
  - `__init__.py` `main()`: env-configured (`LIVE_AUDIO_ZMQ_CONNECT`, `ICECAST_HOST`,
    `ICECAST_PORT`, `ICECAST_SOURCE_USER`, `ICECAST_SOURCE_PASSWORD`).
  - Dockerfile: `python:3.11-slim` + apt `ffmpeg` + uv.
  - `compose.yaml`: `icecast` (port 8000 published) and `live-audio` services wired up,
    both profiles resolve cleanly with `docker compose config`.
- 16 tests passing (`feeder`, `service`, `subscriber`).
- **Build- and runtime-verified (2026-08-08).** `live_audio`'s image builds clean and its
  ffmpeg confirms `libvorbis` encode support. The `icecast2` binary name assumption in the
  Dockerfile's `CMD` was correct (`dpkg -L icecast2 | grep bin` → `/usr/bin/icecast2`), but
  building and actually *running* the Icecast image surfaced two real bugs neither `docker
  build` nor a syntax check would have caught:
  1. `icecast.xml`'s header comment used `--` (this repo's normal em-dash style) inside an
     XML comment, which is illegal there (XML comments can't contain `--` anywhere in the
     body) — Icecast refused to start with a parser error. First fix attempt still had a
     literal `"--"` inside a *sentence about* the restriction, which is still `--` as far
     as the XML parser cares; had to remove the sequence entirely, not just reword around
     it.
  2. icecast2 refuses to run as root as a built-in safety check (unrelated to the
     `<changeowner>` config directive). Fixed by adding `USER icecast2` to the Dockerfile —
     the Debian package already creates that system user with correct ownership on
     `/var/log/icecast2`, and port 8000 needs no special privilege to bind.
  After both fixes: `curl http://localhost:8000/status.xsl` → `HTTP 200` from a real
  running container, and the full 7-service `docker compose up` stack (sdr-rx, same-decoder,
  live-audio, icecast, redis, mosquitto, timescaledb) came up together with live-audio
  logging `"subscribed to tcp://sdr-rx:5555, pushing to icecast:8000"` and staying up.

**Not started / open:**
- Verification against a real ffmpeg process actually encoding to a real Icecast
  mountpoint *with real audio flowing through it* and playing back in a browser — the
  server itself and the encode path are now confirmed working independently, but not yet
  connected end to end with genuine RF-sourced audio.

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
- **2026-08-07** — Implemented every remaining Phase 1 item that doesn't require physical
  RTL-SDR hardware: ZMQ PUB publisher (`bus.py`), tmpfs ring buffer (`ring_buffer.py`),
  health signal (`health.py`), host-prerequisite assertion (`prerequisites.py`),
  multi-dongle serial-addressing config parsing (`capture.py`), and the `DevicePipeline`
  that wires DC-block → channelize → per-channel discriminate → ring-buffer write + ZMQ
  publish + health sample, unit tested end to end via a fake sample source
  (`pipeline.py`). `SoapySDRDevice` itself is written but only exercised for its
  clear-failure path (bindings not installed) — real device I/O still needs target
  hardware. Wired the new entrypoint (`__init__.py`) and `compose.yaml`'s `sdr-rx` service
  (env vars, tmpfs mount); `docker compose config` verified for both profiles. 34 new
  tests, 69 total passing in `services/sdr_rx`. Remaining Phase 1 work is entirely
  hardware-blocked: SoapySDR system package + USB passthrough in Docker/compose, and
  live-hardware verification (all seven WX channels, Pi 5 CPU headroom, host blacklist
  cycle).
- **2026-08-07** — At the user's explicit request, pushed past the normal "prove phase N
  before starting N+1" rule to get the whole stack hardware-bring-up-ready in one pass, not
  just sdr-rx: fixed a real bug found along the way (ZMQ topics were keyed on channel only,
  so two dongles/sites would collide on the same `same.WX5` topic — added `site` into the
  topic and header in `bus.py`/`pipeline.py`, 70 sdr_rx tests still green). Finished Phase
  1's remaining non-hardware work: SoapySDR-capable Dockerfile (switched to
  `debian:bookworm-slim` + apt + `uv venv --system-site-packages`, to avoid mixing apt's
  compiled SoapySDR bindings with a separately-built Python interpreter), device
  enumeration (`SDR_RX_LIST_DEVICES`, `make sdr-devices`), `/dev/bus/usb` passthrough, and
  a checked-in udev rule (`deploy/udev/`) — 71 sdr_rx tests. Built Phase 2
  (`services/same_decoder`: ZCZC parser, tier lookup, dedup, multimon-ng subprocess
  wrapper, ZMQ subscriber, orchestration, Dockerfile, compose wiring — 26 tests) and Phase
  3 (`services/live_audio` + `deploy/icecast/`: picked Icecast over MediaMTX per the design
  doc's own stated tradeoff, ffmpeg feeder, ZMQ subscriber, orchestration, Dockerfile,
  compose wiring — 16 tests). 113 tests passing across all three services (`make test`);
  `docker compose config` resolves cleanly for both profiles with all 7 services. None of
  the new Docker images are build-verified (no daemon in this sandbox) and none of the RF
  path is hardware-verified — every such gap is called out explicitly in each phase's notes
  above rather than implied by a status label. Added a "Hardware bring-up" runbook to the
  repo root README (host prerequisites → `make sdr-devices` → `SDR_RX_DEVICES` → verify via
  Icecast listen + same-decoder RWT log) as the intended next real-world step.
- **2026-08-08** — A Docker daemon turned out to be available in this sandbox after all
  (`dockerd` binary present, network egress worked once the sandbox's proxy CA was trusted
  inside build containers — a local-only workaround, not committed anywhere). Used it to
  actually build and run all four images (`sdr-rx`, `same_decoder`, `live_audio`,
  `icecast`) and the full 7-service `docker compose up` stack, closing out every "not
  build-verified" caveat written the day before. This surfaced three real, previously
  invisible bugs, all now fixed: (1) `same_decoder/tiers.py` crash-looped every container
  on import — `DEFAULT_DATA_DIR`'s `.parents[4]` was a module-level constant that only
  resolves in a full source checkout, not the flattened `/app/src/...` tree Docker actually
  ships; made lazy, only computed when `load()` doesn't get an explicit `data_dir` (28
  tests, up from 26). (2) `deploy/icecast/icecast.xml`'s comment used `--`, illegal inside
  XML comments, so Icecast refused to parse its own config. (3) icecast2 refuses to run as
  root; added `USER icecast2` (Debian's package already creates that user with correct log
  directory ownership). Also fixed `compose.yaml`'s `sdr-rx` service: `restart:
  unless-stopped` was crash-looping it even on its intentional, documented clean-exit path
  ("no devices configured"); changed to `restart: on-failure`, verified against a real
  container that it now stays stopped on exit 0 and would still retry on exit 1. Confirmed
  the single highest-risk assumption from the day before directly: `import SoapySDR`
  genuinely resolves inside `uv venv --system-site-packages`, and `SoapySDRUtil --info`
  shows the rtlsdr module loading. The only thing still not testable in this sandbox is
  `/dev/bus/usb` passthrough itself, since this VM has no USB subsystem at all (not a code
  question, an environment one) — confirmed everything else with that one line stubbed out
  locally, then restored it unchanged before committing. 115 tests passing (`make test`).
