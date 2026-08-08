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

**Status:** Done (2026-08-08)

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

- **Live-hardware verified (2026-08-08):** a user ran the real stack on a Raspberry Pi 5
  (8 GB RAM) with a genuine RTL-SDR dongle over `/dev/bus/usb` passthrough — all seven WX
  channels (WX1–7) came up as distinct Icecast mounts (`services/live_audio`, Phase 3),
  not just the channelizer's synthetic-tone unit tests. The `WX7` mount carries a real,
  audible NOAA Weather Radio broadcast; at `LO_HZ + (2+0.5)×25 kHz = 162.550 MHz` that's
  KIG98, matching master-prompt.md §12's Portland-WFO-area guess exactly — confirms that
  open item empirically instead of leaving it an assumption. `/dev/bus/usb` passthrough and
  the host-prerequisite check (`prerequisites.py`) both ran clean against a real host (no
  `dvb_usb_rtl28xxu` conflict was present to trigger on this Pi, so the block-and-recover
  branch itself is still only unit-tested, not forced for real — not a blocker, since the
  exit criterion is the check running cleanly on real hardware, which it did).

**Nice-to-have, not blocking** (roadmap.md's Phase 1 goal list includes this, but it isn't
part of the stated exit criteria, which are now all met):
- `make bench-channelizer` CPU-headroom numbers on this actual Pi 5 — not yet run.

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
  Phase 2 exit criteria) — **still open as of 2026-08-08** despite Phase 1/3 going live on
  real hardware: the same user confirmed real, audible NOAA Weather Radio audio on the
  `WX7` mount (Phase 1/3), but that's voice audio, not a SAME/EAS burst — nothing has
  actually been decoded by multimon-ng yet, confirmed or otherwise (it's fed every NWR
  channel continuously per `same-decoder`'s `service.py`, so it's already listening on
  `WX7`, just hasn't seen a header air). NWR's own Required Weekly Test (RWT) is still the
  natural first real-world check (repo root README bring-up runbook step 7) — worth
  checking `docker compose logs same-decoder` for a `SameEvent` JSON line around the local
  transmitter's scheduled RWT time, or after any real activations.

---

## Phase 3 — Live audio

**Status:** Done (2026-08-08)

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

- **Live-hardware verified (2026-08-08):** a user confirmed real, RF-sourced audio playing
  back in a browser through a real Icecast mountpoint (`WX7`, see Phase 1's note) — the
  last open item (real ffmpeg encode, real mountpoint, real audio, real playback, all
  connected end to end) is closed.

---

## Phase 4 — Segment capture + local STT

**Status:** In Progress (2026-08-08) -- started ahead of Phase 2's real-audio verification
at the user's explicit direction (Phase 2's own SAME-decode-from-real-audio confirmation is
lower priority than forward progress right now); the design doc's own dependency note below
still holds design-wise, it's just not gating implementation order here.

**Done:**
- `services/segment_capture`, a new uv-managed service:
  - `boundary.py`: duplicated (not imported -- service boundary, CLAUDE.md), narrower
    version of `same_decoder.parser`'s ZCZC regex (just event code + FIPS, no tiers/dedup)
    plus `is_eom()` for the `NNNN` end-of-message marker `same_decoder` doesn't currently
    detect at all.
  - `multimon.py`, `subscriber.py`: identical in shape to `same_decoder`'s own -- this
    service runs its *own* multimon-ng against the same `same.<site>.<channel>` feed,
    independently of `same_decoder`'s, per the architecture diagram (§2) drawing both as
    siblings of `sdr-rx` rather than one depending on the other's output.
  - `ring_reader.py`: read-only counterpart to `sdr_rx.ring_buffer.ChannelRingBuffer`'s
    on-disk format (duplicated file-format knowledge, not imported). Handles the real
    constraint that a capture can run up to the 300s hard timeout while the ring buffer
    only holds a 30s window: `start()` grabs pre-roll once, `read_new()` is then polled
    repeatedly and reports `overrun=True` if a gap is ever unrecoverable (already
    overwritten) rather than silently splicing across it.
  - `tone.py`: 1050 Hz attention-tone-end detector -- a single-frequency DFT correlation
    per fixed window (mathematically a Goertzel filter's result for a fixed window, simpler
    to vectorize since the audio's already fully buffered). Verified against synthetic
    tone+noise signals, including that a stray sub-`MIN_TONE_SECONDS` blip near 1050 Hz
    (e.g. an AFSK symbol) doesn't get mistaken for the real 8-11s tone. Returns `None`
    rather than guessing when no clear run is found -- a wrong trim point is worse than no
    trim, same posture as the hallucination guard downstream.
  - `writer.py`: resamples ring-rate audio to stt_worker's 16 kHz mono s16le uniform
    contract before writing the WAV (duplicated from `sdr_rx.resample`), so `stt_worker`
    needs no format-conversion code of its own.
  - `recorder.py`, `bus.py`, `service.py`: per-(site, channel) capture state machine
    (pre-roll -> live-drain -> finalize on EOM or hard timeout) and the capture-ready ZMQ
    publisher handing off to `stt_worker`.
  - Dockerfile: `python:3.11-slim` + apt `multimon-ng` (same package `same_decoder` already
    uses, apt-install step confirmed building in this sandbox).
- `services/stt_worker`, a new uv-managed service implementing exactly one provider,
  `local_whispercpp` -- CLAUDE.md says stay concrete until a second real provider exists to
  generalize from, so there's no `Provider` abstraction yet, just plain modules:
  - `subscriber.py`: ZMQ SUB for `segment_capture`'s `capture.<site>.<channel>` topic.
  - `trim.py`: cuts the WAV at the `voice_start_sample` `segment_capture` computed --
    design doc §6's "trim before inference" step.
  - `whispercpp.py`: subprocess wrapper around whisper.cpp's `whisper-cli` binary,
    requesting its full JSON output (`-oj -ojf`). **Researched rather than assumed, given
    the design doc calls an unguarded transcript this system's worst failure chain:**
    per-segment `no_speech_prob` only landed in whisper.cpp's JSON writer via a 2026 PR
    (`ggml-org/whisper.cpp#2654`), and `avg_logprob` -- the design doc's other named
    metric -- does not appear to be exposed through the CLI's JSON output at all as of this
    writing (it exists internally in the decoder's fallback logic, but isn't wired into the
    JSON writer, and no documented flag requests it). `guard.py` was written to check each
    threshold only when the corresponding field is actually present, rather than hard-fail
    or silently no-op depending on the exact whisper.cpp build.
  - `guard.py`: `no_speech_prob`/`avg_logprob` thresholds (conditional, see above) plus an
    unconditional blocklist regex for classic Whisper hallucinations ("thank you for
    watching," subscribe prompts, subtitle-credit strings) -- the blocklist is the one
    guarantee that holds regardless of whisper.cpp version.
  - `service.py`: wires trim -> whisper.cpp -> guard -> a `LoggingTranscriptSink` (same
    "no Redis Streams/fusion consumer yet, Phase 5" rationale as `same_decoder`'s).
  - `__init__.py`: startup assertion that fails loudly (one clear line, not a traceback --
    the exact bug class fixed in `sdr_rx.__init__` earlier this session) if
    `STT_WORKER_MODEL_PATH` isn't a real file, per design doc §8's "off-grid means
    pre-staged" requirement.
  - Dockerfile: multi-stage, builds `whisper-cli` from source (`git clone --branch v1.9.2`
    + `cmake`) since no apt package exists for whisper.cpp on a Debian stable base as of
    this writing (only landed in Debian *unstable* in January 2026, and is already marked
    for testing-autoremoval) -- same "build our own, no official image/package exists"
    reasoning as `deploy/icecast`. Both build and runtime stages use the same base image,
    so (unlike `sdr-rx`'s SoapySDR ABI concern) there's no interpreter/glibc mismatch risk
    for the copied binary; added `libgomp1` to the runtime stage since whisper.cpp needs
    OpenMP at runtime, not just build time, and `python:3.11-slim` doesn't ship it.
- `compose.yaml`: `sdr-rx`'s ring buffer changed from a private per-container `tmpfs:`
  mount to a named, tmpfs-backed volume (`sdr-rx-ring`) shared with the new
  `segment-capture` service -- this is a real behavior change from Phase 1, required
  because `segment_capture` genuinely needs to read the same backing memory `sdr-rx`
  writes to, not an independent copy. Added `segment-capture` and `stt-worker` services
  (env vars, a `segment-captures` volume shared between them for the WAV handoff, a
  `./models` read-only bind mount for `stt-worker`). `docker compose config` confirmed
  resolving cleanly, including the shared volumes landing on the right services.
- `Makefile`: `fetch-models` implemented for real (was a stub) -- downloads a ggml model
  from `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-<model>.bin` into
  `./models/`, defaulting to `base.en` per master-prompt.md §6's suggested off-grid
  default. `make test` now also runs `segment_capture`'s and `stt_worker`'s suites.
- 63 new tests (38 in `segment_capture`, 25 in `stt_worker`); 191 tests passing (`make
  test`) across all five implemented services.

**Not started / open:**
- Build/runtime verification for both new Dockerfiles -- `segment_capture`'s apt-install
  layer (multimon-ng) was confirmed building in this sandbox, but the `pip install uv` step
  right after it hit this sandbox's known TLS-intercepting-proxy limitation (see the
  2026-08-08 entry earlier in this log) before getting further; `stt_worker`'s
  from-source whisper.cpp build (a `git clone` over HTTPS) was never attempted for the same
  reason -- it would hit the identical wall immediately. Neither is a code defect; both are
  the same previously-documented sandbox artifact.
- Whether whisper.cpp's real JSON output actually matches the researched shape
  (`{"transcription": [{"text", "no_speech_prob", ...}]}`) once a real binary produces it --
  `whispercpp.py`'s parser is written against documentation/source-reading, not a real
  binary's actual output, since no whisper.cpp build has run anywhere in this repo's
  history yet.
- Live-hardware verification (design doc's actual exit criteria): a recorded RWT/RMT (or
  real event) transcribing correctly end to end, offgrid, on target hardware -- blocked on
  Phase 2's still-open "confirm a real decoded SAME header" item, since segment_capture
  only starts a capture when its own multimon-ng sees a ZCZC line. Also open: benchmarking
  actual Whisper RTF against the `base.en`/`small.en` defaults on the Pi 5 now confirmed
  working in Phase 1 (master prompt §12).

**Depends on:** Phase 2 (needs a real decoded SAME header to trigger a capture at all) --
per CLAUDE.md's normal "prove phase N before starting N+1" rule this would have waited, but
implementation was started anyway at the user's explicit direction; the live-hardware exit
criteria above still can't be met until Phase 2's own real-audio gap closes.

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
- **2026-08-08** — Field report: a host set `SDR_RX_DEVICES` to a bare serial (e.g.
  `49435794`, no `site:` prefix) and got an uncaught `ValueError` traceback out of `main()`,
  crash-looping forever under `restart: on-failure` since a malformed static config never
  self-heals by retrying. `parse_device_config`'s validation was already correct — the gap
  was `main()` not catching it. `__init__.py` now catches `ValueError` from
  `parse_device_config`, prints one clear message naming the offending value and the
  expected `site:serial` format plus the `make sdr-devices` pointer, and exits 1 (still a
  real failure, distinct from the intentional "no devices configured" exit 0 path) instead
  of dumping a traceback. Added `tests/test_main.py` covering this path. Also added a
  `make help` target (and made it `.DEFAULT_GOAL`) since a bare `make` previously ran
  `up-offgrid` (`docker compose up --build`) silently -- now it lists targets instead.
  116 tests passing.
- **2026-08-08** — First real end-to-end hardware run, reported by the user: containers up,
  Icecast reachable, NOAA weather radio audibly decoding through the SDR. Two follow-ups
  came out of that: Icecast's status page showing "Unspecified name/description" for every
  mount, and whether a reverse proxy belongs in front of the stack. The reverse proxy is
  already scoped -- master-prompt.md §9 calls for "Docker Compose behind Caddy or NPM" as
  part of Phase 8 (API + web UI, not started, no `api`/`web` service exists yet to proxy
  to) -- so no code changed there, just confirmed the plan isn't lost. Icecast metadata
  was genuinely missing and is now in scope: `services/live_audio` gained a `metadata.py`
  module (`MetadataConfig`/`StreamMetadata`, a `{site}`/`{channel}` name template plus
  global description/genre) and `feeder.py`'s `build_ffmpeg_command` now passes
  `-ice_name`/`-ice_description`/`-ice_genre` to ffmpeg's icecast protocol when given.
  Configurable via env vars (`ICECAST_STREAM_NAME_TEMPLATE`, `ICECAST_STREAM_DESCRIPTION`,
  `ICECAST_STREAM_GENRE`) for the common case, plus an optional YAML file
  (`LIVE_AUDIO_METADATA_CONFIG`) with `site_names`/`channel_names` display-name overrides
  (e.g. the `home` site from `SDR_RX_DEVICES` showing as "Portland Home Station") for
  friendlier per-deployment labels -- mirrors `same_decoder/tiers.py`'s existing
  YAML-for-structured-config, env-var-for-the-rest split. Added `pyyaml` to `live_audio`'s
  deps, wired the new env vars (with a commented-out volume mount example) into
  `compose.yaml`, and confirmed with `POSTGRES_PASSWORD=x docker compose --profile offgrid
  config` that the `{site}`/`{channel}` braces in the template's shell-default syntax
  (`${VAR:-Tocsin {site} {channel}}`) resolve correctly rather than confusing compose's
  brace matching. 12 new tests (`test_metadata.py` plus feeder/service additions), 128
  tests passing (`make test`). Not verified: an actual ffmpeg push showing the new name on
  a real Icecast status page -- this sandbox's Docker build can reach the daemon but not
  PyPI through its proxy without extra CA setup, so the `live-audio` image itself wasn't
  rebuilt here. The unit tests fully cover the ffmpeg-argument-building and config-loading
  logic; real end-to-end confirmation is on the user's already-working hardware host, not
  this sandbox.
- **2026-08-08** — User confirmed live-hardware bring-up results, closing out Phase 1 and
  Phase 3: real RTL-SDR dongle on a Raspberry Pi 5 (8 GB RAM), all seven WX channels
  (WX1–7) came up as Icecast mounts, and real audio is audibly playing back through `WX7`
  in a browser. `WX7`'s center frequency (162.550 MHz) is KIG98, confirming
  master-prompt.md §12's Portland-WFO-area guess empirically. Phase 2 (SAME decode) stays
  **In Progress**: what's confirmed so far is real voice audio on `WX7`, not a decoded
  SAME/EAS header — `same-decoder` is already listening on every channel including `WX7`,
  it just hasn't seen one air yet. Updated both phases' status and notes in this doc;
  `make bench-channelizer` on the real Pi 5 is the only remaining Phase 1 item, and it's a
  "nice to have" against roadmap.md's goal list, not blocking against its actual exit
  criteria.
- **2026-08-08** — At the user's explicit direction, started Phase 4 (segment capture +
  local STT) without waiting on Phase 2's real-audio confirmation. Implemented
  `services/segment_capture` (ring-buffer pre-roll/live-drain capture triggered by its own
  independent ZCZC/EOM detection, 1050 Hz attention-tone boundary detection, WAV writer) and
  `services/stt_worker` (whisper.cpp `local_whispercpp` provider only, per CLAUDE.md's
  "stay concrete" guidance; hallucination guard checking `no_speech_prob`/`avg_logprob`
  only when whisper.cpp's build actually supplies them, found via research to not be
  reliably available, plus an unconditional blocklist). `compose.yaml`'s ring buffer moved
  from `sdr-rx`'s private tmpfs to a named volume shared with the new `segment-capture`
  service; added a `segment-captures` volume and a `./models` bind mount. `Makefile`'s
  `fetch-models` stub is now real. 63 new tests, 191 passing across all five implemented
  services (`make test`). Neither new Dockerfile is build-verified end to end in this
  sandbox -- `segment_capture`'s apt layer (multimon-ng) built fine, but both it and
  `stt_worker`'s from-source whisper.cpp build hit the same previously-documented
  TLS-intercepting-proxy wall this sandbox always hits on pip/git-over-HTTPS. See Phase 4's
  section above for the full list of what's confirmed vs. still open.
