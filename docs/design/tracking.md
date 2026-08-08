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
| 1 | Channelizer | Done | 2026-08-08 |
| 2 | SAME decode end to end | In Progress | 2026-08-07 |
| 3 | Live audio | Done | 2026-08-08 |
| 4 | Segment capture + local STT | In Progress | 2026-08-08 |
| 5 | NWS poller + fusion | In Progress | 2026-08-08 |
| 6 | Dispatcher stage 1 | In Progress | 2026-08-08 |
| 7 | Dispatcher stage 2 + remote STT | In Progress | 2026-08-08 |
| 8 | API + web UI | In Progress | 2026-08-08 |

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

- **2026-08-08:** `sdr-rx`'s container now also runs `same_decoder`, `live_audio`, and
  `segment_capture` (Phases 2-4) as independent, self-restarting processes launched by a new
  `entrypoint.sh`, at the user's request to shrink `compose.yaml`'s container count further.
  All four stay fully separate uv projects with their own tests; see the Session Log entry
  this date for the full reasoning and `services/sdr_rx/README.md`'s "Container" section for
  the mechanics.
- **2026-08-08:** Manual RTL-SDR gain is now `SDR_RX_GAIN_DB` (`.env`/`compose.yaml`,
  default 30 dB), threaded through `main()` into `SoapySDRDevice(gain_db=...)`, at the
  user's request -- previously only changeable by editing `capture.DEFAULT_GAIN_DB` in
  source, despite the design doc and this repo's own README already flagging it as "the
  thing most likely to need adjusting against your actual RF environment." Tuner frequency
  (`channels.LO_HZ`) and sample rate (`capture.SAMPLE_RATE_HZ`) deliberately stayed fixed --
  both are load-bearing channelizer assumptions (the national NWR channel plan and the
  48-bin odd-stacked math), not per-site tuning knobs; see `services/sdr_rx/README.md`'s
  Configuration section for the reasoning. Two new tests
  (`test_main_passes_sdr_rx_gain_db_through_to_the_device`,
  `test_main_defaults_gain_db_when_sdr_rx_gain_db_is_unset`) using a fake `SoapySDRDevice`
  that records its `gain_db` and fails fast, the same shape `main()` already handles for
  "bindings not installed" -- avoids `thread.join()` blocking forever the way a fake that
  actually started a capture thread would. 83 tests passing in `sdr_rx`, up from 81.

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
  checking `docker compose logs sdr-rx | grep same-decoder` for a `SameEvent` JSON line
  around the local transmitter's scheduled RWT time, or after any real activations
  (`same-decoder` stopped being a separate compose service/container on 2026-08-08 — see
  Phase 1's notes and the Session Log).

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

- **2026-08-08:** `live_audio` no longer has its own `compose.yaml` service or Dockerfile --
  it now ships inside `sdr-rx`'s container image as a second process, connecting to sdr-rx
  over `localhost:5555` instead of `tcp://sdr-rx:5555`. See Phase 1's notes and the Session
  Log entry this date.

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

- **2026-08-08:** `segment_capture` no longer has its own `compose.yaml` service or
  Dockerfile -- it now ships inside `sdr-rx`'s container image as a third process, reading
  sdr-rx's ring buffer over a private `tmpfs:` mount instead of the `sdr-rx-ring` named
  volume (removed) that used to share it across two containers. `stt-worker` (still
  separate) now reaches its capture-ready ZMQ socket at `sdr-rx`'s hostname instead of its
  own. See Phase 1's notes and the Session Log entry this date.

---

## Phase 5 — NWS poller + fusion

**Status:** In Progress (2026-08-08) -- at the user's explicit direction, built ahead of
Phase 2's real-audio confirmation to get the whole stack to an end-to-end MVP faster, same
build-order exception as Phase 4. Unlike Phases 2-4, this phase's actual exit criteria
(roadmap.md: "correlation logic verified against recorded fixtures... covering true
matches, near-misses..., and each unmatched state") don't need real hardware or a running
Redis at all -- so unlike those phases, this one **is** fully verified against its stated
exit criteria already, not just unit tested ahead of hardware proof. What's still open is
integration with the real, running system (live Redis, live `same-decoder`/`nws-poller`
output, a real `api.weather.gov` response), which does depend on Phase 2's still-open
real-audio gap for the RF side.

**Done:**
- `services/nws_poller`, a new uv-managed service:
  - `client.py`: `NwsAlertsClient`, ETag-conditional GET against `api.weather.gov/alerts/active`.
    Verified the actual API contract against the API's own published OpenAPI spec
    (`api.weather.gov/openapi.json`) rather than assuming: confirmed `area` takes exactly
    one state/marine-area code per request (not comma-separated, not repeatable -- `zone`
    supports repetition, `area` doesn't), so polling multiple states means one request per
    area, each with its own tracked ETag. Injectable GET callable, same testability pattern
    as `same_decoder.multimon`'s injectable subprocess command.
  - `parser.py`: GeoJSON feature -> `CapAlert` dataclass, including `geocode.SAME` (the
    field that makes direct FIPS-set correlation against SAME headers possible with no
    county-name lookup in between -- design doc §5) and `parameters.VTEC`.
  - `tracker.py`: `(id, sent)` dedup -- `/alerts/active` returns the full active-alert
    snapshot on every successful poll, not a delta, so without this every still-active
    alert would be re-emitted to `fusion` on every single cycle for as long as it stays
    active.
  - `redis_sink.py`: publishes to Redis Stream `tocsin:cap_alerts`
    (`RedisStreamCapAlertSink`), `LoggingCapAlertSink` fallback when no Redis URL is
    configured -- same seam pattern as every other phase's `LoggingXSink`.
  - `service.py`/`__init__.py`: polling loop wiring, env-configured
    (`NWS_POLLER_USER_AGENT`, `NWS_POLLER_AREAS`, `NWS_POLLER_INTERVAL_SECONDS`,
    `NWS_POLLER_REDIS_URL`); refuses to start with a clear message if the (API-required)
    User-Agent or area list is missing, and a single bad poll cycle logs and continues
    rather than crash-looping the process (network flakiness is the expected case for every
    hybrid-only component, not exceptional -- design doc §8).
  - 19 tests, all against a fake HTTP getter and a fake Redis client -- no real network or
    Redis in this sandbox.
- `services/same_decoder`: added `redis_sink.py` (`RedisStreamEventSink`, publishes to
  `tocsin:same_events`) implementing the phase's actual durability requirement (design doc
  §5: "Both paths write raw events to Redis Streams before fusion sees them") that earlier
  phases explicitly deferred ("no Redis Streams/fusion consumer yet -- that's Phase 5", see
  `LoggingEventSink`'s old docstring). `__init__.py` now picks the Redis sink when
  `SAME_DECODER_REDIS_URL` is set, falling back to the existing `LoggingEventSink`
  otherwise so local/test runs are unaffected. 1 new test, 29 total (up from 28).
- `services/fusion`, a new uv-managed service -- the correlation logic itself:
  - `mapping.py`: loads `data/same_to_cap.yaml`, reusing `same_decoder.tiers`'s
    lazy-default-data-dir fix verbatim (a module-level `.parents[N]` constant crash-looped a
    container once already this build -- see Phase 2's notes -- not repeating that here).
  - `correlator.py`: the actual predicate from design doc §5 -- event-code match (via the
    mapping) AND FIPS-set intersection AND issue-time overlap within a default ±5 min
    tolerance. `SameEventIn.received_at` (decode-time UTC timestamp) stands in for SAME's
    own year-less `JJJHHMM` issue time -- NWR is a live broadcast, so decode time and issue
    time are seconds apart in practice, and this sidesteps year-boundary ambiguity
    `JJJHHMM` alone can't resolve without more context.
  - `confidence.py`: mode-relative confidence table (design doc §5's explicit requirement)
    -- `RF_ONLY` scores high off-grid (the only possible state, not a warning sign) and
    lower in hybrid (the API lagged or disagreed); `API_ONLY` is the reverse, and scores 0
    off-grid as a defensive placeholder since `nws-poller` never runs there to produce one.
  - `store.py`: `AlertStore`, an event-driven in-memory correlation state machine --
    `ingest_same`/`ingest_cap` each scan currently-open alerts of the *opposite* source type
    for a match (linear scan, deliberate: even a busy evening produces a handful of open
    alerts, not thousands -- no index needed yet). A match promotes both to one `CONFIRMED`
    `Alert` with both sources; no match opens a new `RF_ONLY`/`API_ONLY` alert. Explicitly
    not handled yet (documented in the module's own docstring, not silently skipped): a
    second SAME event or CAP update reissue for an already-`CONFIRMED` alert opens a new
    Alert rather than attaching to the existing one -- multi-site RF-RF and CAP-update
    correlation aren't part of the design doc's stated SAME<->CAP correlation key.
  - `redis_bus.py`: `StreamConsumer`, consumer-group durability over both streams (design
    doc §5: "If fusion crashes mid-event it resumes from the consumer group rather than
    losing an alert"). Verified this actually works, not just plausible-sounding: wrote a
    faithful in-memory fake of Redis's consumer-group semantics (`tests/fake_redis_streams.py`
    -- `">"` delivers an entry exactly once per consumer, `"0"` replays that consumer's own
    still-pending entries) and a test that has a handler genuinely raise mid-processing,
    confirms the entry was never acked, reconnects a *second* `StreamConsumer` under the
    same consumer name, and confirms the crash-orphaned entry gets replayed and processed.
    Also confirmed a *different* consumer name does **not** see another consumer's pending
    entries, which drove a real design decision: `FUSION_CONSUMER_NAME` defaults to a fixed
    string (`"fusion"`), not a hostname -- a hostname-derived default would silently break
    crash recovery across container *recreation* (new hostname each time), whereas a fixed
    name survives it since Redis's pending-entries list persists in Redis, not the
    container. Documented as an explicit "at least once, not exactly once" tradeoff
    (matching the design doc's own stated acceptance of this) rather than building
    duplicate-suppression that isn't asked for.
  - `__init__.py`: env-configured (`TOCSIN_MODE`, `TOCSIN_DATA_DIR`, `FUSION_REDIS_URL`,
    `FUSION_CONSUMER_NAME`); this is the first service in the repo to actually read
    `TOCSIN_MODE` in code rather than only via compose profile selection.
  - 33 tests. `tests/fixtures.py` builds realistic `SameEventIn`/`CapAlertIn` fixtures
    (Multnomah/Clackamas FIPS, a real-shaped TOR SAME header, a real-shaped CAP Tornado
    Warning payload) and `test_correlator.py`/`test_store.py` cover every case the
    roadmap's stated exit criteria name: a true match, a near-miss on county, a near-miss on
    event code, a near-miss on time-window tolerance, a SAME code with no CAP equivalent
    (never matches, by construction), and both unmatched states (`RF_ONLY`, `API_ONLY`) in
    both arrival orders (RF-first and CAP-first).
- `compose.yaml`: wired `same-decoder`'s `SAME_DECODER_REDIS_URL`, added `nws-poller`
  (hybrid-only profile, per design doc §8) and `fusion` (both profiles) services. Found and
  fixed one real bug this surfaced: `NWS_POLLER_USER_AGENT`'s first draft used compose's
  hard-required `${VAR:?message}` syntax, which correctly demanded a value under the
  `hybrid` profile -- but compose interpolates every service's environment during `config`
  resolution regardless of which `--profile` was actually selected, so it also blocked
  `offgrid` startup even though `nws-poller` never runs there. Confirmed both ways with a
  real `docker compose config` run (`POSTGRES_PASSWORD=x TOCSIN_MODE=offgrid docker compose
  --profile offgrid config` failed before the fix, succeeded after). Fixed to the same
  empty-default-plus-app-level-check pattern `SDR_RX_DEVICES` already established, since
  that pattern is exactly what avoids this class of bug. `docker compose config` now
  resolves cleanly for both profiles with no required-var footguns, confirmed with and
  without every hybrid-only env var set.
- `Makefile`: `test` target now also runs `nws_poller` and `fusion`. `.env.example`:
  documented the two new hybrid-only vars.
- 244 tests passing across all seven implemented services (`make test`), up from 191.
- **2026-08-08:** `nws-poller` no longer has its own `compose.yaml` service or Dockerfile --
  it now ships inside `fusion`'s container image as a second process, launched by
  `services/fusion/entrypoint.sh` only under `TOCSIN_MODE=hybrid`. Still a fully separate uv
  project with its own tests (`make test` unchanged); see the Session Log entry this date for
  the full reasoning.

**Not started / open:**
- Neither new Dockerfile is build-verified -- no Docker daemon in this authoring sandbox
  this session (unlike the 2026-08-08 session earlier in this log that had one). Both
  Dockerfiles are plain `python:3.11-slim` + `uv sync` with no apt/from-source step (unlike
  `sdr-rx`/`stt-worker`), so the risk profile is lower than those, but "lower risk" isn't
  "verified."
- Not verified against a real Redis instance, real `same-decoder`/`nws-poller` output, or a
  real `api.weather.gov` response -- `nws_poller`'s response-shape assumptions come from the
  API's own published OpenAPI spec, not a live call. Worth an early real-network check once
  Redis and both producers are actually running together.
- `AlertStore` doesn't yet persist anything -- `LoggingAlertSink` is the only sink, same "no
  consumer yet" seam pattern as every prior phase's default sink. Phase 8's `api` service is
  the eventual TimescaleDB-backed consumer.
- The two deliberately-out-of-scope gaps named in `store.py`'s and `redis_bus.py`'s own
  docstrings (no CONFIRMED-alert re-attachment; at-least-once redelivery can double-ingest
  across a crash) are open items, not bugs -- revisit once real traffic shows how often they
  matter.

**Depends on:** Phase 2 (RF-side events) for full integration testing; per roadmap.md, the
correlation logic itself was explicitly designed to be developed and proven against fixtures
without it, which is what actually happened here.

---

## Phase 6 — Dispatcher stage 1

**Status:** In Progress (2026-08-08) -- same build-order exception as Phases 4-5: built at the
user's explicit direction to keep pushing toward a whole-stack MVP, ahead of Phase 2's
real-audio proof. Depends on Phase 5's `tocsin:alerts` output, which itself is fully proven
against its own exit criteria already (see Phase 5's notes) -- so the only genuinely open
dependency chain left is Phase 2's real-SAME-decode confirmation, plus this phase's own
hardware requirement (a real Meshtastic node) that no phase before it needed.

**Done:**
- `services/fusion` gained the producer half of the handoff this phase needed:
  `redis_sink.py` (`RedisStreamAlertSink`, publishes every canonical `Alert` to
  `tocsin:alerts`), wired as `main()`'s sink (previously `LoggingAlertSink`-only, since
  nothing consumed it yet). Extracted the JSON serialization logic that used to live inline
  in `store.py`'s `LoggingAlertSink` into `serialize.py` so both sinks share one definition
  of the wire shape. 3 new tests, 36 total in fusion (up from 33).
- `services/dispatcher`, a new uv-managed service -- stage 1 only (template message, serial
  Meshtastic, idempotency, rate limiting); stage 2 (LLM enrichment) and the Meshtastic MQTT
  ack-fallback leg are Phase 7, per roadmap.md's own phase split:
  - `fips.py`: loads `data/fips.csv` for county/state names, strips SAME's `PSSCCC`
    subdivision digit down to the plain 5-digit FIPS the file keys on. This is the first
    phase to actually read `fips.csv` for its stated purpose (templating) rather than just
    carrying it as unused reference data.
  - `message.py`: the deterministic stage-1 template (design doc §7) -- verified it renders
    the design doc's own example string byte-for-byte
    (`TOR WARN | Multnomah,Clackamas OR | exp 2145Z | RF`), plus a ≤140-byte truncation path
    exercised against a synthetic 31-FIPS SAME header (the format's actual maximum). A FIPS
    code outside `fips.csv`'s seeded Portland-WFO area falls back to showing the raw code
    rather than dropping the county silently.
  - `dedup.py`/`rate_limit.py`: near-duplicate suppression and a ~6/hr-burst-3 token bucket
    per design doc §7's airtime budget, same TTL-eviction shape as `same_decoder.dedup`.
  - `idempotency.py`: Redis-persisted `SET NX` claim so a dispatcher restart doesn't
    re-send. SAME carries no ETN, so the design doc's example key
    `(event, fips_set, etn, stage)` substitutes the SAME header's own `raw_header` for the
    ETN slot (it already uniquely encodes event/FIPS/purge/issue-time/callsign as one
    string) rather than threading a new field through `same_decoder`/`fusion` to reconstruct
    an equivalent tuple by hand.
  - `meshtastic_serial.py`: a thin injectable wrapper around the real `meshtastic` PyPI
    package's `SerialInterface.sendText`. Verified against the library's actual installed
    source in this session (`inspect.signature` against the real package, not just
    documentation) rather than assumed: `sendText(text, wantAck=True, onResponse=...)`
    matches exactly, and the library has no built-in blocking "wait N seconds for ack"
    primitive, so this wrapper builds one with a `threading.Event` to match the design
    doc's explicit "wait 15s for ack" behavior. Tests cover ack, nak, timeout, and a
    response genuinely fired from a background thread (`threading.Timer`), not just a
    synchronous callback.
  - `redis_bus.py`: consumer-group durability over `tocsin:alerts`, same pattern (and the
    same tested crash-replay behavior) as `fusion.redis_bus`.
  - `service.py`: `Stage1Dispatcher` wires tier gating -> dedup -> rate limit -> idempotency
    claim -> send, in that specific order -- documented and tested as a deliberate choice,
    not arbitrary: idempotency is claimed *last*, immediately before the send, because its
    24h Redis claim is a one-way door. Claiming it earlier and then having a later gate
    reject the alert would permanently strand a real alert as "already sent" for 24h despite
    it never having actually gone out -- a bug class this ordering (and a dedicated test)
    rules out by construction.
  - `__init__.py`: env-configured (`TOCSIN_DATA_DIR`, `DISPATCHER_REDIS_URL`,
    `DISPATCHER_CONSUMER_NAME`, `MESHTASTIC_SERIAL_DEV_PATH`); fails loudly and exits 1 (not
    a raw traceback) if the FIPS table can't load or the Meshtastic serial interface can't
    open, mirroring `sdr_rx`/`stt_worker`'s established startup-assertion pattern for a
    missing hardware/config dependency.
  - 45 tests: every module above plus an end-to-end `Stage1Dispatcher` suite (Tier
    A/B/C gating, near-duplicate suppression before a rate-limit token is spent, a burst of
    3 sending followed by a 4th being rate-limited, a send exception not propagating while
    still correctly claiming idempotency, and -- the roadmap's stated exit criteria in
    miniature -- a second identical header not being resent even across a fresh
    `Stage1Dispatcher` instance sharing the same fake Redis, simulating a restart).
- `compose.yaml`: added `dispatcher` (both profiles, per design doc §2's architecture table
  -- stage 1 is deterministic and zero-dependency by design, so it runs identically
  off-grid). Single serial device passthrough (`MESHTASTIC_SERIAL_DEVICE`, defaults
  `/dev/ttyUSB0`), unlike `sdr-rx`'s whole-USB-bus passthrough -- a Meshtastic node
  enumerates as one stable serial device, not a bus-relative path that shifts across
  replugs. `restart: on-failure`, matching `segment-capture`'s precedent for "missing
  required hardware/mount is a real, retriable failure," not `sdr-rx`'s "deliberately
  supported absence" pattern. `Makefile`'s `test` target and `.env.example` updated.
- 292 tests passing across all eight implemented services (`make test`), up from 244.

**Not started / open:**
- No MQTT ack-fallback (Phase 7) -- a serial send exception or ack timeout isn't retried by
  any other path yet; the idempotency key is still claimed at that point (deliberately, see
  `service.py`'s docstring), so a transient serial failure means that exact alert won't be
  retried until its 24h claim expires. Accepted as this phase's scope boundary, not missed.
- Tier B alerts (`data/same_event_codes.yaml`: "MQTT only") have no MQTT egress path at all
  yet -- not clearly scoped to a named phase in `docs/design/roadmap.md` as written (Phase 7
  only names the Meshtastic MQTT *ack-fallback* leg specifically, not a general Tier-B
  broadcast). Worth a design-doc/roadmap clarification pass before Phase 7, not a dispatcher
  bug.
- A SAME header whose FIPS codes span more than one state only shows the first state seen in
  the stage-1 message (`message.py`) -- Portland WFO's real OR+WA coverage means this could
  actually happen, not just a theoretical edge case.
- Live-hardware verification (roadmap's actual exit criteria: "a decoded SAME event reaches
  a real Meshtastic node over serial... and a dispatcher restart does not re-send it") is
  entirely open -- no Meshtastic node, no Docker daemon, and no Redis instance in this
  authoring sandbox this session. `meshtastic_serial.py`'s wrapper was checked against the
  real package's actual signatures (not just docs) specifically because this gap exists and
  couldn't be closed by running the real hardware path.

**Depends on:** Phase 5 (needs `tocsin:alerts`, which is fully proven against its own exit
criteria already) and, per roadmap.md, Phase 2 (a real decoded SAME header to dispatch in the
first place) -- both still open for the same reason every phase since 2 has flagged: no real
RF has been decoded in this repo's history yet, only real *voice* audio (Phase 1/3's
live-hardware verification).

---

## Phase 7 — Dispatcher stage 2 + remote STT

**Status:** In Progress (2026-08-08) -- same build-order exception as Phases 4-6: built at
the user's explicit direction to finish Phase 7 before moving to Phase 8, ahead of Phase 2's
real-audio proof. Verified against its own stated exit criteria already, the same way Phase 5
was: roadmap.md's literal wording ("killing the LiteLLM endpoint mid-run degrades stage 2
silently with stage 1 still delivered" and "circuit breaker opens after N consecutive
failures and recovers") is exercised directly in `services/dispatcher/tests/
test_stage2_dispatcher.py`, not just plausible by design.

**Done:**
- Closed a real gap discovered while scoping this phase: `stt_worker`'s `GuardedTranscript`
  carried `event_code`/`fips_codes` but not the SAME header's own `raw_header` or a `tier`
  value -- stage 1 gets both for free via `fusion`, but `segment_capture` runs its own
  independent SAME-header parse (Phase 4's deliberate design) that never touched either.
  Without them, stage 2 would have needed a fuzzy, collision-prone way to match a transcript
  back to "which alert does this enrich." Fixed at the source instead of working around it in
  `dispatcher`:
  - `services/segment_capture` gained `tiers.py` (mirrors `same_decoder/tiers.py` exactly,
    including its lazy-default-data-dir fix) and now threads `tier` (looked up from its own
    parsed event code) and `raw_header` (`boundary.MessageStart.raw`, previously captured
    but dropped at the `CaptureResult` boundary) through `CaptureResult` ->
    `CapturePublisher`'s JSON payload. `SegmentCaptureService` takes an optional `TierTable`
    now (`None` falls back to an empty table, i.e. Tier B for everything -- safe default for
    existing callers/tests written before this). 8 new tests, 46 total (up from 38).
  - `services/stt_worker`'s `GuardedTranscript` gained `tier`/`raw_header`, passed straight
    through from the capture payload in `handle_capture`.
- `services/stt_worker`, the two other Phase 7 deliverables the roadmap names for this
  service:
  - **Redis Streams producer:** `redis_sink.py` (`RedisStreamTranscriptSink`, publishes to
    `tocsin:transcripts`), the same optional-Redis-URL seam `same_decoder`/`nws_poller`
    already established.
  - **`remote_http` provider + `STT_CHAIN` race:** `transcript.py` extracts the
    provider-agnostic `Transcript`/`Segment` types out of `whispercpp.py` (which now
    re-exports them for backward compatibility) now that there's a second real provider to
    share them with -- CLAUDE.md's own stated exception to "stay concrete." `remote_http.py`
    implements the OpenAI-compatible `POST /v1/audio/transcriptions` shape design doc §6
    names explicitly. `service.py`'s `TranscriptionWorker._transcribe` implements "race,
    don't chain": local always runs to completion (the floor); on Tier A captures only, when
    a remote provider is configured, both run concurrently via a `ThreadPoolExecutor`, and
    remote wins if it returns non-empty text within a budget measured *from the start of the
    race* (not restarted after local finishes). Deliberately simplified from the design
    doc's literal "with a better score" wording -- a real cross-provider confidence
    comparison isn't implementable against a generic OpenAI-compatible endpoint, whose
    standard response is just `{"text": ...}` with none of whisper.cpp's
    `no_speech_prob`/`avg_logprob` guaranteed (documented explicitly in both `service.py`'s
    and `README.md`'s text, not silently assumed away). A real bug avoided during
    implementation, not found after the fact: an early draft used a `with
    ThreadPoolExecutor(...)` block, whose implicit `shutdown(wait=True)` on exit would have
    blocked the caller until the *slow* remote thread actually finished even after the code
    had already "given up" waiting via the budget timeout -- silently turning
    `remote_budget_seconds` into a lie. Fixed by managing the pool explicitly with
    `shutdown(wait=False)`, with a test (`test_local_wins_when_remote_exceeds_budget`) that
    asserts on wall-clock elapsed time to prove the caller isn't blocked.
  - 13 new tests, 38 total (up from 25).
- `services/fusion` gained the producer half of the handoff this phase needed:
  `redis_sink.py` (`RedisStreamAlertSink`, publishes every canonical `Alert` to
  `tocsin:alerts`), wired as `main()`'s sink. Extracted the JSON serialization logic that
  used to live inline in `store.py`'s `LoggingAlertSink` into `serialize.py` so both sinks
  share one definition. 3 new tests, 36 total (up from 33). *(Landed alongside Phase 6's own
  work, listed here since it's this phase's actual dependency, not Phase 6's.)*
- `services/dispatcher`, completing both of design doc §7's remaining pieces:
  - **`egress/` package** (introduced now that there are two real egress mechanisms to
    group, matching design doc §9's suggested layout): `meshtastic_serial.py` moved here
    unchanged from Phase 6; `meshtastic_mqtt.py` (new) publishes Meshtastic's real MQTT
    downlink JSON schema to `msh/{region}/2/json/mqtt/` -- verified against Meshtastic's own
    MQTT integration docs this session (topic format, required channel named "mqtt" with
    downlink enabled, `{"from", "type": "sendtext", "payload"}` schema), not guessed;
    `dispatch.py`'s `DualPathSender` implements the design doc's serial-primary,
    MQTT-fallback flow, gated on `TOCSIN_MODE=hybrid` (design doc §8's connectivity contract
    -- `dispatcher` is the second service in this repo, after `fusion`, to actually read
    `TOCSIN_MODE` in code). `Stage1Dispatcher` was refactored to send through `DualPathSender`
    instead of the serial client directly; its own tests and outcome-reason vocabulary
    updated to match ("serial"/"mqtt_fallback"/"serial_no_ack"/"mqtt_fallback_failed"
    replacing Phase 6's placeholder "sent"/"no_ack").
  - **Stage 2**: `litellm_client.py` (LiteLLM's real OpenAI-compatible chat-completions
    contract, verified against LiteLLM's own docs -- `/chat/completions`, `Authorization:
    Bearer`, `choices[0].message.content`; hard 3s timeout per the design doc),
    `circuit_breaker.py` (Redis-persisted consecutive-failure counter; opens for a cooldown
    after N failures; recovery is TTL-driven, not a dedicated half-open state -- once the
    open marker's Redis TTL lapses, the next call is simply allowed to try again),
    `stage2_guard.py` (length/ASCII/no-newline validation on LiteLLM's *output*, distinct
    from `stt_worker.guard`'s hallucination guard on its *input*), and `Stage2Dispatcher` in
    `service.py` wiring: tier gate -> transcript-guard gate -> cheap `already_claimed()` peek
    (avoids paying for an LLM call re-enriching something already fully dispatched) ->
    circuit-breaker gate -> LiteLLM call -> output guard -> the real, side-effecting
    `idempotency.claim()` (last, immediately before the send, same "claim last" principle
    Phase 6 established for stage 1 and this module's own docstring explains again for
    stage 2's slightly different gate shape).
  - `models.py` gained `TranscriptIn`/`parse_transcript` alongside the existing
    `RFAlertIn`/`parse_rf_source`; `redis_bus.py`'s `AlertStreamConsumer` (already generic
    over `stream=`) now also serves `tocsin:transcripts`, reusing the exact same
    crash-replay-tested class rather than writing a second one.
  - `__init__.py`: stage 2 is built only when `DISPATCHER_LITELLM_BASE_URL` is set: unset
    means `tocsin:transcripts` is never even consumed (chose design doc §8's "omitted
    entirely" option for offgrid over its "template-only" alternative, since the former
    needs zero additional code).
  - 27 new tests (circuit breaker, LiteLLM client, stage-2 guard, `Stage2Dispatcher`, the
    MQTT client, `DualPathSender`, plus `Stage1Dispatcher`'s tests updated for the egress
    refactor), 82 total in `dispatcher` (up from 45).
- `compose.yaml`: `segment-capture` and `stt-worker` gained `TOCSIN_DATA_DIR`/data mount and
  `STT_WORKER_REDIS_URL`/`STT_CHAIN`/remote-provider env vars respectively; `dispatcher`
  gained `TOCSIN_MODE`, MQTT gateway env vars, and LiteLLM env vars, plus a `mosquitto`
  dependency. `docker compose config` confirmed resolving cleanly for both profiles, with
  minimal env and with every new hybrid-only var set at once (a lesson learned from
  Phase 5's `NWS_POLLER_USER_AGENT` bug: every new var here uses the same
  empty-default-plus-app-level-check pattern, none use compose's hard-required `:?`).
- 350 tests passing across all eight implemented services (`make test`), up from 292.

**Not started / open:**
- Everything named in the three services' own READMEs as unverified: no real Meshtastic
  node, no real MQTT gateway configuration, no real LiteLLM/OpenAI-compatible endpoint, no
  real remote STT endpoint, no real Redis instance, and no Docker daemon in this sandbox this
  session -- every wire contract in this phase was verified against real published specs
  (Meshtastic's MQTT docs, LiteLLM's docs, the OpenAI API shape) rather than guessed, but
  "spec-verified" isn't "live-verified."
- Tier B's general MQTT broadcast path (distinct from the ack-fallback leg this phase does
  build) is still unscoped in roadmap.md, called out again in `dispatcher/README.md`.
- A SAME header spanning more than one state still only shows the first state in stage-1's
  message (carried over from Phase 6, unchanged).

**Depends on:** Phase 4 (transcript) and Phase 6 (stage 1) per roadmap.md -- both already
built in this repo (see their own sections), so this phase's only remaining real-world
dependency is the same one every phase since 2 has: no real SAME header has been decoded from
actual RF in this repo's history yet.

---

## Phase 8 — API + web UI

**Status:** In Progress (2026-08-08) -- same build-order exception as Phases 5-7: built at
the user's explicit direction ("finish 7 and then move to 8") ahead of Phase 2's real-audio
proof. The largest single phase so far -- the first to touch TimescaleDB at all, the first
FastAPI service, and the first TypeScript in this repo.

**Done:**
- Found and fixed a real bug in `sdr_rx` while wiring health data into the UI, not introduced
  by this phase: `HealthTracker` was shared across every site's `DevicePipeline` in a
  multi-dongle setup but keyed samples on `channel` alone -- two sites' `WX5` would silently
  collide, the same bug class already fixed once for `sdr_rx.bus`'s ZMQ topics (this doc,
  2026-08-07). Fixed by keying on `(site, channel)` throughout `health.py`, with a regression
  test reproducing the exact collision.
- `services/sdr_rx` gained `spectrum.py`: the 41 non-NWR bins (design doc §3: "the 41 unused
  bins feed the spectrum/waterfall display as free occupancy data") computed from the
  channelizer's already-full 48-bin output that `DevicePipeline.process()` was previously
  discarding -- genuinely free, no new DSP work, just reading what was already being thrown
  away. Correctly reindexes raw FFT columns to odd-stacked bin order via the same `k %
  NUM_BINS` mapping `DevicePipeline` already used per-NWR-bin (tested explicitly for both a
  positive-k and a negative-k wraparound case, since getting this silently wrong would have
  produced a plausible-looking but mislabeled spectrum). Throttled to ~1/sec, published as a
  latest-snapshot Redis key (not a stream -- a waterfall display wants "now," not history).
  `redis_sink.py` gained `RedisStreamHealthSink` (`tocsin:health`, a real time series worth
  keeping) alongside the spectrum snapshot sink. 9 new tests, 81 total in `sdr_rx` (up from
  72).
- `services/api`, a new FastAPI service and the first thing in this repo to actually write to
  the `timescaledb` compose service:
  - `schema.sql` (applied idempotently at startup, `db.ensure_schema`): `alerts` (upserted by
    id, since `fusion` republishes the same alert on every state transition) and
    `health_samples` (an actual TimescaleDB hypertable via `create_hypertable` -- the one
    table in this schema where a real time-series database earns its keep over plain
    Postgres). No ORM/migration framework -- raw asyncpg, matching this codebase's established
    minimalism; there's no schema-evolution story yet to build tooling for.
  - `redis_bus.py`: an async port of `fusion`/`dispatcher`'s consumer-group `StreamConsumer`
    (`redis.asyncio` throughout, `asyncio.create_task` for the background poll loop), serving
    both `tocsin:alerts` and `tocsin:health`. Crash-replay tested against an async version of
    the same hand-written faithful Redis-streams fake used elsewhere.
  - `ingest.py`/`sse.py`: newly ingested alerts upsert into Postgres *and* fan out live to any
    connected `/alerts/stream` client via an in-process `Broadcaster` (one `asyncio.Queue` per
    client) -- deliberately not Redis pub/sub, since `api` has no horizontal-scaling story yet
    to justify it.
  - `app.py`: `GET /alerts`, `/alerts/stream` (SSE), `/health`, `/spectrum`, `/spectrum/{site}`,
    `/stats` (alert-state counts plus the `RF_ONLY`/`API_ONLY` divergence rate -- design doc
    §5's stated "best single health metric for the whole system"). `create_app()` takes
    already-constructed `pool`/`redis_client` rather than building them in a `lifespan`
    callback, specifically to keep route logic testable with fakes and no async context
    manager to trigger or bypass.
  - Found one real testing-infrastructure trap, not a product bug: an early `/alerts/stream`
    test opened a live `TestClient.stream()` connection against the endpoint's intentionally-
    infinite generator and hung indefinitely -- `TestClient`'s stream context manager doesn't
    reliably cancel that on exit. Killed the hung process, replaced the test with one that
    confirms the route is registered correctly without opening a live connection, since the
    actual pub/sub logic (`Broadcaster`) already has full direct coverage in `test_sse.py`.
  - 36 tests: `db.py` (schema application, upsert/insert queries, the ISO-string ->
    `datetime` conversion asyncpg requires for `timestamptz` params -- JSON has no native
    datetime type, and asyncpg does not parse strings implicitly), `redis_bus.py`,
    `sse.py`, `spectrum.py`, `ingest.py`, `config.py`, and `app.py` (via FastAPI's
    `TestClient` against fake Postgres/Redis).
- `web/`, a new Vite + TypeScript frontend -- vanilla, no framework (the design doc names
  "Vite + TypeScript" without one, and there's no way to visually verify UI polish in this
  authoring sandbox regardless of framework choice, so this stayed proportionate):
  `src/api.ts` (REST fetch helpers + `subscribeToAlerts` via native `EventSource`, no SSE
  library needed), `src/views/{alerts,health,spectrum,stats}.ts` (hand-authored DOM
  manipulation -- the alert feed's `upsert()` replaces an already-rendered alert in place
  rather than duplicating it when `fusion` republishes the same id on a state transition; the
  spectrum view colors the 7 NWR channel bins distinctly from the 41 spectrum-only bins), and
  `src/main.ts` wiring SSE (push) for alerts against 5s polling (no push feed yet) for
  health/spectrum/stats. `nginx.conf` proxies `/api/*` to the `api` service in production
  (stripping the prefix, `proxy_buffering off` for SSE specifically -- buffering would defeat
  the point of a live feed). `npm run build` (`tsc --noEmit` then `vite build`) is the only
  verification performed -- confirmed real by running it against the live npm registry in
  this session, not assumed.
- `compose.yaml`: `sdr-rx` gained `SDR_RX_REDIS_URL`; `api` (Postgres DSN built from the
  already-required `POSTGRES_PASSWORD`, so no new required-var footgun) and `web` (nginx on
  8080, proxying to `api`) added, both profiles. `docker compose config` confirmed resolving
  cleanly for both.
- Caught up two stale spots in the root README while touching this area: the "Build order"
  section still described Phase 1 as hardware-unverified and didn't mention Phases 5-8 at
  all (both facts had changed several sessions ago without the README being updated to
  match); fixed to reflect actual current status per this doc, and the `make test` service
  list was missing every service added since Phase 4.
- 395 tests passing across all nine implemented Python services (`make test`), up from 350,
  plus `web`'s clean type-check-and-build.
- **2026-08-08:** `web` no longer has its own `compose.yaml` service, Dockerfile, or nginx
  container -- `services/api`'s Dockerfile now builds it as a stage and `app.py` serves the
  built `dist/` as static files at `/`, mounted after every API route so the route table is
  unchanged. `web/src/api.ts`'s default base URL moved from `/api` to same-origin unprefixed
  accordingly. See the Session Log entry this date for the full reasoning.

- **2026-08-08 (UI overhaul):** the frontend was surfacing roughly a third of what the
  system already knew, and three whole classes of information had nowhere to go at all.
  Closed all of it, plus the transcript-storage gap this doc had flagged as open.
  - **Service liveness (new).** Nothing in the repo published a heartbeat, so nothing could
    tell a stopped `fusion` from a quiet night. Each of the eight non-`api` services now
    SETEXes `tocsin:status:<service>` from its own main loop (`heartbeat.py`, duplicated
    per service per CLAUDE.md, generated from one template and unit tested once in
    `fusion`); `api` writes its own from an async task. `GET /services` compares the live
    keys against a checked-in expected set *for the current mode* -- listing only the keys
    that exist would render a crashed service as absent rather than broken, which is the
    exact failure the endpoint exists to catch. `nws_poller` is excluded from the expected
    set under `offgrid` (design doc §8) and its heartbeat carries last-success/last-error,
    since a poller failing every call to api.weather.gov is otherwise indistinguishable
    from a quiet night. `live_audio` and `segment_capture` gained optional Redis URLs for
    this and nothing else -- their real output still goes over Icecast/ZMQ.
  - **Transcripts (the open item from this phase's first pass).** `transcripts` table,
    a fourth consumer on `tocsin:transcripts`, and `GET /transcripts?raw_header=` --
    `raw_header` being the only identifier shared between an alert's RF source and a
    transcript. `stt_worker`'s `GuardedTranscript` gained `wav_path`, threaded straight
    through from `segment_capture`'s payload, so `GET /captures/{name}` can serve the
    original audio next to the text. That endpoint takes the basename only and re-checks
    containment after resolution: `wav_path` arrives from a Redis payload, so trusting it
    as a filesystem path would have made it an arbitrary-file read.
  - **Dispatch outcomes (new).** `dispatcher` sent to the mesh and recorded nothing
    queryable, making "did that warning actually go out?" answerable only from container
    logs. `RedisStreamDispatchLog` publishes every stage-1/stage-2 decision to
    `tocsin:dispatches` (slotting into the `DispatchLog` Protocol seam that already
    existed), `api` stores it and serves `GET /dispatches`, and `/stats` gained a
    sent-vs-skipped summary. The negatives are the valuable half -- `skipped_rate_limited`,
    `serial_no_ack`, `skipped_circuit_open` are all "an alert existed and nothing reached
    the mesh." The `dispatches` table deliberately has no primary key: a rate-limited
    attempt followed by a later successful one is two real events, not a duplicate.
  - **SSE carries everything now.** `/alerts/stream` became `/events` with named event
    types (`alert`, `health`, `transcript`, `dispatch`), which let the frontend drop its
    polling timers for health entirely -- a channel going dead (design doc §3's primary
    liveness signal for the whole SDR path) used to wait up to 5s to reach the screen. The
    broadcaster's per-client queue is now bounded and drops oldest-first, so one asleep tab
    can't grow the process's memory.
  - **Other new endpoints.** `/system` (mode -- the UI cannot honestly describe an empty
    CAP column without knowing whether the deployment polls NWS at all), `/health/history`
    (`time_bucket`-aggregated, `dead` `BOOL_OR`'d rather than averaged so a partly-dead
    bucket still reads dead), `/streams` (Icecast `status-json.xsl` merged with
    `live_audio`'s heartbeat mount list -- Icecast drops a mount whose source died, which
    is the moment you most want to see it), and `/reference` (`data/`'s event codes and
    FIPS table, so the UI shows "Multnomah, OR" and a tier badge instead of `041051`).
  - **`web/` rebuilt.** Status bar (mode/services/dispatch), expandable alert cards showing
    RF and CAP provenance side by side with the RF-to-API latency, county names, tier
    badges, active/expired split and sorting, relative timestamps, per-panel error states,
    filters, a merged transcript/dispatch activity log, Icecast players, health sparklines,
    and a fixed-scale scrolling waterfall replacing the bar chart that rescaled to each
    frame's own min/max (which made a carrier appearing look identical to the noise floor
    dropping). Every alert field that used to be fetched and discarded is now on screen:
    `sources[]` was arriving in the browser and being thrown away wholesale.
  - **First real browser render in this repo's history.** Served the built `dist/` plus a
    stub API matching `services/api`'s response shapes to headless Chromium at 1440px and
    420px: no console or page errors, no horizontal page scroll at either width, filters
    and card expansion and the per-alert transcript/dispatch fetch all confirmed working,
    search input keeps focus across re-renders, tab title badges active Tier A alerts. Two
    real bugs were found this way and fixed -- the waterfall drew rows bottom-anchored
    while its own comment said newest-at-top, and `/health/history` had been added but
    never actually called, leaving the sparkline column permanently blank.
  - **466 tests** across the nine Python services (up from 395) plus `web`'s clean
    type-check-and-build. `compose.yaml` wires the new env/volumes for `api` (data dir,
    captures volume read-only, Icecast host/public URL, mode) and the two new heartbeat
    Redis URLs; YAML parses cleanly, though no Docker daemon was available this session to
    re-run `docker compose config`.
  - **Still not verified:** nothing here has run against a real Postgres, Redis, Icecast,
    or live upstream producer. The browser render used a stub API, and no real SAME header
    has ever been decoded from actual RF in this repo's history -- unchanged from every
    prior phase.

**Not started / open:**
- No auth (design doc §9: "reverse proxy + Argon2id local backend auth") -- out of scope for
  this phase, which is about the data path, not the deploy-behind-Caddy story.
- Not verified against a real Postgres, Redis, browser, or live upstream producer anywhere in
  this phase -- verified against fakes, fixtures, and (for `web`) a real `npm`/`tsc` run
  against the live registry, but no real page has ever been rendered against a real backend.
- `/alerts` has no pagination beyond `limit` (no cursor/offset) -- fine at current expected
  alert volumes.

**Depends on:** Phase 5 (alert store) and Phase 1 (health signal) per roadmap.md -- both
already built (Phase 5 fully proven against its own exit criteria; Phase 1 live-hardware
verified). The only remaining real dependency is the same one every phase since 2 has
flagged: no real SAME header has been decoded from actual RF in this repo's history yet, so
the alert feed this UI displays has never shown a real RF-sourced alert end to end.

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
- **2026-08-08** — At the user's explicit direction ("let's get an MVP of the whole project
  up and running, working end to end"), built Phase 5 in full: `services/nws_poller` (new --
  ETag-conditional `api.weather.gov` client verified against the API's own OpenAPI spec,
  GeoJSON parser, active-alert dedup tracker, Redis Streams sink), `services/fusion` (new --
  event-code/FIPS/time-window correlator, mode-relative confidence, an in-memory
  `AlertStore` state machine, and a Redis consumer-group durability layer whose
  crash-recovery replay is actually tested, not just asserted, against a hand-written
  faithful fake of Redis's stream semantics), and `services/same_decoder` gained the
  `RedisStreamEventSink` the design doc's durability requirement (§5) needed and earlier
  phases had explicitly deferred to "Phase 5." Unlike Phases 2-4, this phase's stated exit
  criteria (roadmap.md: correlation verified against fixtures covering true matches,
  near-misses, and each unmatched state) don't depend on real hardware at all, and are fully
  met as of this session, not just unit-tested-ahead-of-proof. Found and fixed one real bug
  along the way: `docker compose config` interpolates every service's environment
  regardless of which `--profile` is selected, so the first draft's hard-required
  `NWS_POLLER_USER_AGENT` (`${VAR:?...}`, correct in isolation for `hybrid`) was silently
  blocking `offgrid` startup too, even though `nws-poller` never runs there -- exactly the
  class of regression CLAUDE.md's connectivity rule exists to prevent. Fixed to the same
  empty-default-plus-app-level-loud-fail pattern `SDR_RX_DEVICES` already uses; confirmed
  both profiles resolve cleanly with `docker compose config`, with and without every
  hybrid-only var set. `Makefile`'s `test` target and `.env.example` updated. 244 tests
  passing (`make test`), up from 191. No Docker daemon in this sandbox this session, so
  neither new image is build-verified (lower risk than `sdr-rx`/`stt-worker`'s images since
  both are plain `python:3.11-slim` + `uv sync`, no apt/from-source step, but not the same
  as verified); also not yet run against a real Redis instance or real `api.weather.gov`
  traffic. See Phase 5's section above for the full done/open breakdown.
- **2026-08-08** — Continued the same MVP push into Phase 6: `fusion` gained
  `redis_sink.py` publishing every canonical `Alert` to `tocsin:alerts` (extracted its JSON
  serialization into a shared `serialize.py` in the process), and `services/dispatcher` (new)
  implements stage 1 in full -- deterministic template message, near-duplicate suppression,
  a token-bucket rate limiter, Redis-persisted idempotency (keyed on the SAME header's own
  `raw_header` since SAME carries no ETN), and a `meshtastic` PyPI wrapper checked against
  the real installed package's actual signatures (`inspect.signature`, not just
  documentation) since no physical Meshtastic node exists in this sandbox to verify against
  directly. Found a real design bug while writing `service.py` and fixed it before it ever
  shipped: an early draft claimed the idempotency key as the *first* gate for simplicity,
  which would have permanently stranded any alert that got that far and then failed a later
  gate (rate limit, dedup) as "already sent" for 24h despite never actually being
  transmitted -- reordered so idempotency is claimed *last*, immediately before the send,
  and added a dedicated test (`test_send_exception_does_not_propagate_and_idempotency_is_
  still_claimed`) that would fail if that ordering ever regressed. `compose.yaml` gained the
  `dispatcher` service (both profiles, single serial-device passthrough, `restart:
  on-failure`). 292 tests passing (`make test`), up from 244. Entirely unverified against
  real hardware or a real Redis this session -- no Meshtastic node, no Docker daemon, no
  Redis instance available; see Phase 6's section above for the complete breakdown of what
  that leaves open.
- **2026-08-08** — Finished Phase 7 in the same MVP-push session, at the user's explicit
  direction ("let's finish 7 and then move to 8"). Closed a real gap found while scoping
  stage 2: `segment_capture`'s independent SAME-header pipeline (a deliberate Phase 4 design
  choice) never carried the raw header text or a tier value through to `stt_worker`, so
  stage 2 had no precise way to identify which alert a transcript belonged to the way stage
  1 does. Fixed at the source (`segment_capture` gained its own `tiers.py` and now threads
  `raw_header`/`tier` through `CaptureResult` -> `stt_worker`'s `GuardedTranscript`) rather
  than building a fuzzier matching heuristic downstream. Built `stt_worker`'s `remote_http`
  provider and `STT_CHAIN` race (local always completes as the floor; remote races
  concurrently on Tier A only, within a budget measured from the start of the race) and its
  `tocsin:transcripts` Redis producer; `fusion` gained the `tocsin:alerts` producer
  `dispatcher` needed. Built `dispatcher`'s `egress/` package (a real `meshtastic_mqtt.py`
  downlink publisher verified against Meshtastic's actual MQTT integration docs -- exact
  topic and JSON schema, not approximated -- plus `dispatch.py`'s serial-then-MQTT
  `DualPathSender`, mode-gated per design doc §8) and stage 2 in full (`litellm_client.py`
  verified against LiteLLM's real API docs, a Redis-persisted `circuit_breaker.py`, and
  `stage2_guard.py` for LiteLLM's own output). Caught one real bug before it shipped, in
  `stt_worker`'s race logic: an early draft's `with ThreadPoolExecutor(...)` block would have
  silently blocked past the remote budget on its implicit `shutdown(wait=True)`, waiting for
  a slow remote thread to finish even after giving up on it -- fixed with an explicit
  `shutdown(wait=False)` and a wall-clock-timed regression test. Both of this phase's named
  roadmap exit criteria are exercised directly, not just asserted plausible:
  `test_stage2_dispatcher.py` kills a fake LiteLLM mid-run and confirms stage 2 degrades
  silently while never touching egress, and drives the circuit breaker through open ->
  cooldown -> recovery in one test. 350 tests passing (`make test`), up from 292. Nothing in
  this phase touched real Meshtastic/MQTT/LiteLLM/remote-STT infrastructure or a real Redis
  -- every wire contract was verified against real published specs this session, but that's
  "spec-verified," not "live-verified"; see Phase 7's section above for the full breakdown.
- **2026-08-08** — Finished Phase 8 in the same session, at the user's explicit direction
  ("finish 7 and then move to 8"): the API + web UI milestone, and by far the largest single
  phase so far -- the first to write to TimescaleDB, the first FastAPI service, the first
  TypeScript in this repo. Found and fixed a real latent bug in `sdr_rx` while wiring health
  data into the new UI (not caused by this phase, just surfaced by finally using the data for
  something): `HealthTracker` was shared across every site's `DevicePipeline` but keyed
  samples on `channel` alone, so two dongles/sites would silently collide on the same channel
  name -- the identical bug class already fixed once for this service's own ZMQ topics
  (2026-08-07 entry above). Fixed by keying on `(site, channel)` throughout, with a
  regression test reproducing the exact collision. Added `sdr_rx.spectrum`: the 41 spectrum-
  only bins design doc §3 describes, computed for free from data `DevicePipeline.process()`
  was already discarding, correctly reindexed through the same `k % NUM_BINS` mapping
  `DevicePipeline` uses per-channel (verified against both a positive- and negative-k
  wraparound case, since a silent reindexing bug would have produced a plausible-looking but
  mislabeled spectrum display). Built `services/api` (FastAPI, raw asyncpg against a
  checked-in `schema.sql`, async Redis consumer groups feeding both Postgres and a live SSE
  fan-out) and `web/` (vanilla Vite+TypeScript, no framework -- proportionate given this
  sandbox can't visually verify UI polish regardless of framework choice). Hit and fixed one
  real test-infrastructure trap along the way: an `/alerts/stream` test using
  `TestClient.stream()` against the endpoint's intentionally-infinite SSE generator hung the
  whole test run indefinitely; killed the hung process and replaced it with a route-
  registration check, relying on `test_sse.py`'s already-thorough direct coverage of the
  underlying pub/sub logic instead. Also caught the root README's "Build order" section badly
  out of date (still described Phase 1 as hardware-unverified, didn't mention Phases 5-8 at
  all) and fixed it to match this doc, since a stale root README undermines the very
  "where are we" tracking this file exists to provide. 395 tests passing across all nine
  Python services (`make test`), up from 350, plus a clean `web` type-check-and-build
  confirmed against the live npm registry. Nothing in this phase ran against a real Postgres,
  Redis, or browser -- see Phase 8's section above for the complete breakdown.
- **2026-08-08** — At the user's request, consolidated `compose.yaml` from 14 containers to
  12 under the `hybrid` profile (13 to 12 under `offgrid`, where only the `web` merge counts
  -- `nws-poller` was already hybrid-only, so it was never one of `offgrid`'s 13 to begin
  with). Confirmed against real resolved service lists, not just arithmetic: `docker compose
  --profile offgrid config --services` and `--profile hybrid config --services` both list
  exactly the same 12 names now (`api`, `dispatcher`, `fusion`, `icecast`, `live-audio`,
  `mosquitto`, `redis`, `same-decoder`, `sdr-rx`, `segment-capture`, `stt-worker`,
  `timescaledb`) -- the offgrid/hybrid split that used to show up as `nws-poller`
  existing-or-not now lives entirely inside `fusion`'s container instead. Two merges, both
  deployment-only -- no service's own Python package was touched, and neither
  crosses a service boundary with a Python import (CLAUDE.md's "communicate over ZMQ, Redis,
  MQTT, HTTP, not imports" rule still holds): (1) `web` merged into `api` -- `services/api`'s
  Dockerfile gained a `node:22` build stage for `web/` (build context moved to the repo root
  so it can reach both directories) and `app.py`'s `create_app` now optionally mounts the
  built `dist/` as static files at `/`, registered after every API route so explicit routes
  still win their exact path; `web/src/api.ts`'s default `API_BASE_URL` changed from `/api`
  to same-origin unprefixed now that there's no nginx proxy stripping that prefix. Removed
  `web/Dockerfile` and `web/nginx.conf`. (2) `nws-poller` merged into `fusion` -- both stay
  fully independent `uv` projects/venvs (own `pyproject.toml`, own tests, still run
  separately via `make test`), built into one image by `services/fusion`'s Dockerfile (also
  now repo-root-context) and launched as two OS processes by a new `entrypoint.sh`: fusion
  runs via `exec` as the container's foreground/PID-1 process (so it still owns the
  container's exit status and receives `docker stop`'s SIGTERM directly), while nws-poller
  runs in a self-restarting background loop, started only when `TOCSIN_MODE=hybrid` --
  replacing the old `profiles: [hybrid]` compose-level gate with the exact kind of runtime
  `TOCSIN_MODE` branch CLAUDE.md's connectivity contract asks for, so a bad/missing
  `NWS_POLLER_USER_AGENT` under hybrid retries in place instead of taking fusion down with
  it. `compose.yaml`'s `api` service kept its host port at 8080 (now mapped straight to
  the container's 8000 instead of nginx's 80) so the bring-up runbook in the root README
  didn't need to change. Added `API_STATIC_DIR` config plus 4 new tests to `services/api`
  covering the static mount (root 404s with no static dir configured, serves `index.html`
  when one is, and API routes still win over it) and its config default/override/disable --
  40 tests passing there, up from 36; `services/fusion` and `services/nws_poller` untouched
  internally, still passing their existing suites (36 and 19 respectively). A Docker daemon
  turned out to be reachable in this session (same as the 2026-08-08 entry above that first
  found one) -- used it to actually build and run both merged images, not just resolve
  `docker compose config`. `docker top` on the merged `fusion` container confirmed
  `nws-poller` is genuinely absent under `TOCSIN_MODE=offgrid` and present under `hybrid`;
  with `NWS_POLLER_USER_AGENT` deliberately left unset under hybrid, confirmed `nws-poller`
  retry-loops in place ("retrying in 5s") while `fusion`'s own process stays up throughout --
  the exact failure-isolation behavior the merge was designed to preserve. For the merged
  `api` container, ran it against real `redis` and `timescaledb` containers and confirmed
  with `curl`: `GET /` returns the built SPA's `index.html`, its JS asset resolves with
  `content-type: application/javascript`, and `GET /alerts`, `/health`, `/stats` all still
  return the expected JSON -- static mount and API routes coexisting for real, not just
  argued about in a docstring. (Building required trusting this sandbox's TLS-intercepting
  proxy CA inside the build -- a local-only workaround via a scratch Dockerfile/cert copy,
  same pattern as this file's very first 2026-08-08 entry; nothing from that workaround was
  committed.) Went no further than these two: folding `same-decoder`/`segment-capture` into `sdr-rx` or
  `dispatcher` was considered and rejected, since it would give up the independent
  `on-failure`/`unless-stopped` restart policies and device-passthrough isolation those
  services are deliberately built around.
- **2026-08-08** — Revisited the rejection immediately above, at the user's request: the
  restart-policy/isolation cost is real, but so is the argument for merging anyway --
  `same-decoder`, `live-audio`, and `segment-capture` are already one failure domain in
  practice (all three are useless without `sdr-rx` producing anything, and none of them
  crash-loops the others today), and one container's interleaved, per-line-prefixed logs
  (each of the four already prints its own `"<name>: ..."` prefix, an existing convention,
  not new) are easier to read when diagnosing one failure than four `docker compose logs`
  invocations. Folded `same_decoder`, `live_audio`, and `segment_capture` into `sdr-rx`'s
  container (deliberately left `stt-worker` out -- see below), taking `compose.yaml` from
  12 containers to 9. All four stay fully independent uv projects with their own
  `pyproject.toml`/tests (`make test` unchanged) -- no cross-package Python import, same
  boundary rule as the merges above.
  - `services/sdr_rx/Dockerfile` now builds all four into separate venvs on one
    `debian:bookworm-slim` image (`python:3.11-slim` won't do -- sdr-rx's apt-installed
    SoapySDR bindings need to stay on Debian's own interpreter, see the Dockerfile's own
    comment; the other three don't need `--system-site-packages` but happily share the same
    base and get `multimon-ng`/`ffmpeg` from the same apt layer).
  - New `entrypoint.sh` is meaningfully more involved than the fusion+nws-poller one: none
    of the four processes is a single "always required" foreground owner the way `fusion`
    is for `nws-poller`, because the repo root README's bring-up runbook *requires*
    same-decoder/live-audio/segment-capture to keep running even when sdr-rx has no dongle
    configured at all. All four now run as independent, self-restarting background loops
    under `set -m` (so each gets its own process group), with a `trap`/`cleanup` that sends
    `kill -TERM -- "-$pid"` (the process-group form, not a plain `kill $pid`) to each on
    `docker stop` -- without that, SIGTERM would hit only the idle loop shell, not the
    actually-running `uv run <service>` underneath it, and `docker stop` would hang out its
    full timeout before falling back to SIGKILL. sdr-rx's own loop is the one with real
    exit-code-dependent logic, ported from this file's very first 2026-08-08 entry (the
    `restart: on-failure`-vs-`unless-stopped` bug fixed there): exit 0 ("no devices
    configured") stops that one loop from retrying; exit 1 retries. `SDR_RX_LIST_DEVICES`
    (`make sdr-devices`) is special-cased at the top of the script to `exec` straight into
    just sdr-rx's listing codepath, skipping the other three entirely -- without this,
    `make sdr-devices` would launch the whole stack and then hang forever instead of
    printing serials and exiting, since the merged entrypoint's default path never returns.
  - `compose.yaml`: `same-decoder`/`live-audio`/`segment-capture`'s env vars folded into
    `sdr-rx`; their `*_ZMQ_CONNECT` defaults (both the compose env var and each service's
    own `DEFAULT_ZMQ_CONNECT` constant in source) changed from `tcp://sdr-rx:5555` to
    `tcp://localhost:5555`, since they're the same container now, not a separate one
    reaching sdr-rx by service name. The `sdr-rx-ring` named tmpfs volume is gone --
    segment-capture reading sdr-rx's ring buffer only ever needed a *shared* volume because
    they were different containers; merged, a private `tmpfs:` mount on sdr-rx does the same
    job with one less top-level volume. `stt-worker` (kept separate -- see below) now
    connects to `tcp://sdr-rx:5556` instead of `tcp://segment-capture:5556`, since
    segment-capture no longer has its own hostname; that constant changed in
    `stt_worker/__init__.py` too.
  - **`stt-worker` deliberately excluded**, per an explicit scoping question this session:
    it has no hardware dependency (unlike the other four), a completely different resource
    profile (CPU-bound whisper.cpp transcription vs. this container's I/O-bound RF
    plumbing), the heaviest single build in the repo (from-source whisper.cpp), and its own
    independent "missing model file" restart story -- it doesn't share sdr-rx's fate the way
    same-decoder/live-audio/segment-capture do.
  - Updated `services/sdr_rx/README.md` (new "Container" section), `same_decoder/README.md`,
    `live_audio/README.md`, `segment_capture/README.md` (each gained a short "ships inside
    sdr-rx's container now" note plus corrected `*_ZMQ_CONNECT` defaults),
    `services/stt_worker/README.md`, and the root README's hardware bring-up runbook (step
    4's "same-decoder/live-audio/icecast stay up while sdr-rx exits" description no longer
    holds -- the whole container now stays `Up`, with sdr-rx's own process just logging that
    it stopped retrying; step 7's `docker compose logs -f same-decoder` became `docker
    compose logs -f sdr-rx | grep same-decoder` since that's no longer a separate service).
    Also corrected a `docker compose logs same-decoder` pointer in Phase 2's own "Not
    started / open" notes for the same reason.
  - Test suites for all five touched services (`sdr_rx`, `same_decoder`, `live_audio`,
    `segment_capture`, `stt_worker`) re-run and green, unchanged counts (81/29/28/46/38).
  - `docker compose config` resolves cleanly for both profiles, both now listing the same 9
    services.
  - Build- and run-verified against a real Docker daemon, not just `docker compose config`
    (same local CA-trust workaround as the earlier entry this date, nothing committed): `uv
    venv --system-site-packages` genuinely sees apt's SoapySDR bindings inside this merged
    image (`import SoapySDR` succeeds, `SoapySDRUtil --info` lists the `rtlsdr` factory) --
    confirms the four-projects-on-one-base-image approach doesn't break sdr-rx's ABI
    constraint. Ran the merged container with no `SDR_RX_DEVICES` set: `docker top` showed
    `same-decoder`, `live-audio`, and `segment-capture` all alive with real `uv run <name>`
    children, no `uv run sdr-rx` process anywhere, sdr-rx's own log line read "exited 0 (no
    devices configured) -- not retrying," and `docker ps` still showed the container `Up` --
    exactly the bring-up runbook's intended shape, now produced by one container instead of
    four. `SDR_RX_LIST_DEVICES=1` (the `make sdr-devices` path) exited in under a second with
    only sdr-rx's own listing codepath ever starting, confirming the entrypoint's early
    short-circuit works. `docker stop` on the running container returned in 0.33s with the
    container fully removed and no leftover processes -- confirms `set -m` plus the
    process-group `kill -TERM -- "-$pid"` in `cleanup()` actually reaches the real `uv run
    <service>` processes, not just their loop shells, avoiding a hang out to the stop
    timeout and a SIGKILL fallback.

- **2026-08-08 (frontend/API overhaul):** answered "are we surfacing everything, is there a
  service monitor, can we listen to the Icecast feeds" with: no (about a third), no, and
  not from the UI. Added per-service liveness heartbeats + `GET /services`, transcript
  storage + `GET /transcripts` + `GET /captures/{name}`, a dispatch outcome log +
  `GET /dispatches`, and `/system` `/health/history` `/streams` `/reference`; converted
  `/alerts/stream` to a multi-type `/events` stream; rebuilt `web/` around an expandable
  alert card that shows RF and CAP provenance side by side. First browser render in this
  repo's history (headless Chromium against a stub API), which caught two real bugs. 466
  tests green, up from 395. See the Phase 8 notes above for the full reasoning.

- **2026-08-08:** Remote model selection is now settable from `.env` for both hybrid-only
  LLM/STT paths, at the user's request. `DISPATCHER_LITELLM_MODEL` and
  `STT_WORKER_REMOTE_MODEL` were already read by their services' `__init__.py` and
  documented in the service READMEs, but `STT_WORKER_REMOTE_MODEL` was never passed
  through `compose.yaml` -- so under Docker (the only supported deployment) the remote STT
  model was pinned to `whisper-1` with no way to change it short of editing source. Added
  the compose passthrough, documented both selectors in `.env.example` (neither was there),
  and covered the env-to-client wiring with tests in both services, which had tested the
  clients' `model` argument but never that anything actually supplied it.

- **2026-08-08:** Tocsin can now run with no Meshtastic node attached, at the user's
  request ("some users might just want a way to run this without the meshtastic relay").
  Two things blocked it: Docker refuses to *start* a container whose `devices:` host path
  is absent, so the mapping in `compose.yaml` made a node a hard prerequisite for the whole
  stack -- including the receive-only half that needs no radio -- and `main()` treated a
  serial interface it couldn't open as fatal. Moved the device mapping into a new
  `compose.mesh.yaml` overlay (a list entry in an override can't be unset once the base
  declares it, so a separate file is the only way to make it optional), included by default
  via `COMPOSE_FILE` in `.env`; the overlay also flips `MESHTASTIC_ENABLED`, so dropping it
  is a single switch that removes the mapping and the transmit path together. With mesh
  off, `DualPathSender` skips serial and reports `mesh_disabled` while stage 1 still runs
  in full, so the dispatch log records what would have been sent; the MQTT leg stays
  reachable, since "no local node, gateway elsewhere" is a real deployment. A
  configured-but-missing node is still a loud exit 1.
- **2026-08-08:** Fixed `make down`, which stopped nothing. Every service in `compose.yaml`
  declares `profiles:`, and Compose does not select a profiled service unless its profile is
  active -- so the bare `docker compose down` matched zero services and exited 0 while the
  stack kept running (user-reported, confirmed with `docker compose config --services`).
  Now names both profiles explicitly and adds `--remove-orphans`.

- **2026-08-08:** Implemented the TCP half of design doc §7's "sendText(wantAck=True) over
  **serial/TCP**" -- the spec has always allowed a networked node, but only `SerialInterface`
  was ever wired up, so a node on WiFi/Ethernet was unreachable. Asked for by the user
  ("how do we configure .env to use a networked mesh node over a serial connection").
  `SerialInterface` and `TCPInterface` both derive from `MeshInterface` and expose identical
  `sendText`/`close` (verified against the installed library, along with the
  `TCPInterface(hostname, portNumber=4403)` signature), so the ack-wait logic is
  transport-agnostic: `meshtastic_serial.py` became `meshtastic_node.py` with one
  `MeshtasticNodeClient` behind an `interface_factory` seam and two factories. That is the
  one deliberate deviation from §9's suggested `egress/meshtastic_serial.py` filename --
  naming the module after a single transport would be the misleading half of the spec, and
  it's noted in `egress/__init__.py`. Selected with `MESHTASTIC_TRANSPORT=serial|tcp` plus
  `MESHTASTIC_TCP_HOST`/`_PORT`; a TCP node needs no `devices:` mapping, so it runs on
  `compose.yaml` alone with `MESHTASTIC_ENABLED=true` set by hand rather than via the
  `compose.mesh.yaml` overlay. `EgressResult.path` now carries the actual transport
  (`tcp`/`tcp_no_ack`), so the dispatch log stops calling a network link "serial";
  `node_transport` defaults to `serial`, leaving every existing log value unchanged. A LAN
  node is not an internet dependency and stays valid offgrid -- §8's four gated components
  cover the MQTT fallback leg, not the link to your own node.

- **2026-08-08:** Made the two host-published ports configurable at the user's request
  ("we need to make the front end port and the icecast ports configurable"). `TOCSIN_WEB_PORT`
  (default `8080`) publishes the web UI/API and `ICECAST_PORT` (default `8000`) publishes
  Icecast, both from `.env`; `API_PORT` now also feeds the container side of the api mapping
  instead of being a `"8000"` literal that a changed `API_PORT` would have silently
  desynced. The Icecast side needed more than a compose edit: Icecast reads its listen port
  from XML and has no env configuration, so `deploy/icecast/icecast.xml` became a template
  with an `${ICECAST_PORT}` placeholder rendered by a new `entrypoint.sh` (`envsubst`, with
  an explicit variable list) to `/tmp/icecast.xml` -- `/etc/icecast2` is root-owned and the
  container runs as `icecast2`. Host and container port move together for Icecast on
  purpose: the browser reaches a mount by the host port while `live-audio`/`api` reach it by
  the container port, and both read `ICECAST_PORT`, so splitting them would break playback
  URLs for anyone who hasn't set `ICECAST_PUBLIC_URL` (now documented in `.env.example`
  alongside a new "Ports" section in the root README). Verified with `docker compose config`
  at defaults and at `TOCSIN_WEB_PORT=9090 ICECAST_PORT=8100 API_PORT=8001` (mappings and
  every consumer's env resolve correctly), `sh -n` on the entrypoint, and an XML-parse check
  of the rendered template at both ports -- which caught an illegal `--` inside the XML
  comment added next to the placeholder. Not verified: the built image actually starting
  Icecast on a non-default port, since no Docker daemon is available in this sandbox (same
  standing gap as the rest of the compose stack). Unprivileged `icecast2` caps
  `ICECAST_PORT` above 1024; noted in the Dockerfile and `.env.example`.

- **2026-08-08:** Fixed three startup failures a user hit on a real deployment (pasted
  `docker compose` logs: `api` and `stt-worker` restart-looping, `sdr-rx`'s live-audio and
  segment-capture crash-looping, web UI unreachable).
  1. `live_audio` and `segment_capture` import `redis` for their liveness heartbeat but
     never declared it -- both `pyproject.toml`s were missing `redis>=5.0`, so every start
     died with `ModuleNotFoundError` inside `_build_redis_client()`. The lazy import is
     what hid it: nothing at import time touches `redis`, so the container built clean and
     every unit test passed. Added the dependency (locks regenerated) plus a
     `test_redis_client.py` in each service that calls `_build_redis_client()` with a URL
     set -- `from_url` connects lazily, so it needs no live Redis and fails exactly when
     the dependency goes missing again. `same_decoder` (same container) already declared it,
     which is why only two of the four processes were down.
  2. `api` could not authenticate to Postgres, which is why the web UI was unreachable at
     all -- `api` serves the SPA, so `api` down means no front end. Two changes: compose now
     passes `API_POSTGRES_HOST/PORT/USER/PASSWORD/DB` instead of interpolating
     `postgresql://tocsin:${POSTGRES_PASSWORD}@...` in YAML, and `config.py` percent-encodes
     the parts (verified round-trip through asyncpg's own DSN parser) -- a password
     containing `@`, `:`, `/`, `?`, or `#` used to produce a *different* DSN and fail with
     "password authentication failed" while `.env` was correct. `API_POSTGRES_DSN` still
     wins when set. New `connect.py` then splits transient failures (connection refused,
     `57P03`) from permanent ones: the first are retried for 60s, the second raise
     `PostgresStartupError` with an operator-facing message and exit 1, instead of an
     asyncpg traceback reprinted every few seconds by `restart: on-failure`. The stale-volume
     cause gets named explicitly, since it is the likely one here: Postgres reads
     `POSTGRES_PASSWORD` only when initializing an empty data dir, so editing `.env` after
     the first `up` leaves the old password in the `timescale-data` volume. `timescaledb`
     also gained a `pg_isready` healthcheck and `api` now waits on it
     (`condition: service_healthy`) rather than racing a database that binds its port before
     it is ready.
  3. `stt-worker` exited 1 on a missing model file and let `restart: on-failure` retry,
     reprinting the same line into the shared log stream every couple of seconds. It now
     waits for the file (`await_model`, 15s poll, reminder every 5 min) -- identical
     recovery when a model is dropped into `./models/`, without the noise. An *unset*
     `STT_WORKER_MODEL_PATH` is still an immediate exit 1: nothing to wait for.

  Also added a Troubleshooting section to the root README (UI won't load → check `api`;
  the password fix, with the non-destructive `ALTER USER` form as well as `down -v`; the
  stt-worker wait; librtlsdr's `usb_claim_interface error -6` / `PLL not locked`, which
  appear in the user's log but are benign when the device goes on to open). Verified:
  `docker compose config` on the offgrid profile, and full suites for `api` (100),
  `stt_worker` (43), `live_audio` (33), `segment_capture` (48). Not verified: a real `up`
  against a live Postgres, since this sandbox still has no Docker daemon -- the transient
  vs. permanent split is covered by injected-`connect` unit tests raising real asyncpg
  exception types.

- **2026-08-08:** Restructured `.env.example` at the user's request ("full of comments and
  the whole thing is all over the place"). Same variables, grouped into Core / Ports /
  Radio / Transcription / Meshtastic / Hybrid-only sections and ordered by how often they
  are touched, with the long-form reasoning cut down to one or two lines per var and a
  pointer to the service README that already carries it in full (verified before deleting:
  the networked-node recipe and the drop-the-overlay instructions are both in
  `services/dispatcher/README.md`, the Icecast one-knob-three-uses explanation is in the
  root README's "Ports", gain guidance is in `services/sdr_rx/README.md`). 143 lines to 108.
  One variable added, `STT_WORKER_MODEL_FILE`: `compose.yaml` reads it and the Makefile
  tells you to set it after `make fetch-models STT_MODEL=...`, but it was absent here.
  `MESHTASTIC_ENABLED` deliberately stays out as an active line -- `compose.mesh.yaml`
  reads it as `${MESHTASTIC_ENABLED:-true}`, so an explicit `false` in `.env` would silently
  disable transmit while the device mapping stayed in place; it's mentioned only in the
  `tcp` note where turning it on by hand is actually required. Verified by rendering
  `docker compose config` from the new file with both compose files and the hybrid profile.
