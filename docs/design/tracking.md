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
| 2 | SAME decode end to end | Done | 2026-08-13 |
| 3 | Live audio | Done | 2026-08-08 |
| 4 | Segment capture + local STT | In Progress | 2026-08-08 |
| 5 | NWS poller + fusion | In Progress | 2026-08-10 |
| 6 | Dispatcher stage 1 | In Progress | 2026-08-08 |
| 7 | Dispatcher stage 2 + remote STT | In Progress | 2026-08-10 |
| 8 | API + web UI | In Progress | 2026-08-10 |

---

## Phase 0 — Bootstrap

**Status:** Done (2026-08-07)

Repo layout, `compose.yaml` (offgrid/hybrid profiles, validated with
`docker compose config` — a real daemon was not available to validate `up`), `Makefile`,
`data/*.yaml`/`data/fips.csv` (fips.csv seeded for the Portland WFO area only — see
`data/README.md`), `CLAUDE.md`/`AGENTS.md`, this roadmap/tracking pair.

**2026-08-09:** Added `data/nwr_stations_or.yaml`, the full NWR station listing for
Oregon from weather.gov (callsign, site name, frequency, status, operating WFO), toward
the §12 open item on verifying local transmitter frequencies. Confirms KIG98/Portland on
162.550 as the master prompt's §12 open item already expected. The item's other guess,
KEC91 (Naselle Ridge) on 162.400, is a Washington-side site and outside this
Oregon-scoped list, so it's still unconfirmed by this data — Eugene's KEC42, also on
162.400, is the only Portland-WFO 162.400 station this listing covers. Reference data
only; doesn't replace the empirical waterfall confirmation the open item calls for.

**2026-08-09 (later same day):** Extended that file with `power_watts` and `lat`/`lon` per
station, sourced from a third-party aggregator (radiostation.info) since no NWS page
publishing them was reachable while authoring the file (weather.gov's own per-station pages
are JS-rendered and returned only navigation chrome to a fetch; `nws.noaa.gov`'s equivalent
403'd). Two stations (WZ2522 Carney Butte, WZ2559 Enterprise) have no coordinates anywhere
found -- left `null` rather than guessed, both there and in every consumer of this file (see
Phase 8's entry this date). This is what made the new "nearby NWR stations" UI feature
possible; see that entry for the api/web side.

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

- **2026-08-09:** A live deployment report of `sdr-rx` pegged near 100% CPU on one core (see
  Phase 3's note this date for the audio-quality report that came with it) led to profiling
  `DevicePipeline.process()` end to end rather than guessing. Three unrelated inefficiencies,
  all fixed with no behavior change -- see the Session Log entry this date for the full
  profiled numbers: `resample.py`'s `resample_poly` calls were redesigning their anti-aliasing
  FIR filter (`firwin` + Kaiser window, one ratio ~20,000 taps) from scratch on every chunk
  despite `up`/`down` never changing -- now cached via `lru_cache`, verified numerically
  identical to the uncached path in `test_resample.py`. `ring_buffer.py`'s `write()` called
  `mmap.flush()` every chunk; pointless on the tmpfs this buffer is documented to live on
  (`MAP_SHARED` mappings of the same file don't need msync for cross-process visibility --
  verified empirically and with a new regression test using a second, independent `mmap`
  standing in for `segment_capture`'s reader). `channelizer.py`'s `_demodulate()` called
  `exp()` on every sample of every chunk even though the demodulation ramp only takes
  `2 * num_bins` (96) distinct values -- now a precomputed lookup table gathered by index.
  Combined: ~2.4x throughput improvement on the sandbox benchmark (1.41x -> 3.44x real-time
  margin per dongle). All of `test_channelizer.py`'s strict swept-tone amplitude/phase
  assertions still pass unmodified -- CLAUDE.md's bar for touching this file. 96 tests
  passing in `sdr_rx`, up from 93.

- **2026-08-09 (squelch upgrade):** Replaced `audio_conditioning.Squelch`'s fixed-RMS-
  threshold design with a self-calibrating noise-quieting squelch, ported from
  `d3mocide/op25-downstream`'s `squelch_core.NoiseSquelch` (credited there to Pieter-Tjerk de
  Boer PA3FWM's "Squelch algorithms" technote) -- see the Session Log entry this date for the
  full writeup, including why GNU Radio itself was ruled out as a wholesale replacement.
  Dropped the reference's `disc_gain`/`deviation` normalization (this discriminator's output
  is already unit-gain radians per sample) and its optional DB1NV voice detector (no
  P25/DMR-style voice-vs-data distinction applies to a feed already split from raw SAME
  decode). Kept: a runtime-tracked, rise-only no-carrier reference so `open_db`/`hyst_db` are
  portable dB-relative thresholds instead of one fixed number needing per-site tuning, and the
  4-state (closed/opening/open/hang) machine with a rehold margin that avoids the open<->hang
  chatter a single hysteresis threshold falls into at the boundary. `SQUELCH_REF_POWER_INIT`
  and the 8 kHz noise band were calibrated against this channelizer's *real* DC-block/PFB/
  discriminator chain fed AWGN (not an idealized approximation) -- consistently ~0.62 rad^2
  across all seven NWR bins. Found and fixed one real bug this calibration surfaced: the
  discriminator output for a synthetic test tone needs the baseband *offset* from the LO
  (`(k + 0.5) * 25000` Hz), not `channels.bin_frequency_hz()`'s absolute RF frequency --
  using the latter by mistake in a scratch calibration script produced a wildly aliased
  "carrier" that showed no quieting at all, which is what caught the mistake. Also fixed a
  real bug in the port itself once real signals were used to test it: `noise_power` seeded
  from the same deliberately-low `SQUELCH_REF_POWER_INIT` as the reference caused a strong,
  genuine carrier's low noise-band power to take several `POWER_TAU_MS` windows to smooth in
  from that unrelated starting point, delaying every open decision -- now the first real
  measurement snaps `noise_power` directly instead of smoothing in from an arbitrary seed.
  Config: `SDR_RX_SQUELCH_THRESHOLD` (an absolute number needing per-site tuning) replaced by
  `SDR_RX_SQUELCH_OPEN_DB` (a portable dB value, default 8.0, matching the reference
  algorithm's own default). Verified: `sdr_rx` 102 passed (up from 96) -- new tests include a
  direct port of the reference implementation's own threshold-jitter-doesn't-thrash regression
  test (driving the state machine directly, the same technique its own test suite uses, rather
  than trying to synthesize audio landing on an exact dB value) and two tests running the real
  channelizer chain end to end (AWGN never opens the gate; a clean carrier does), trimmed from
  an initial 3-5s of simulated IQ per case down to 0.75s once the behavior was confirmed stable
  at that length, to keep the suite fast (full suite: 28s -> 9.5s). Not verified: real hardware
  -- the calibration is against this channelizer's own simulated chain, not an actual dongle's
  noise floor, which will differ in absolute terms (though the self-calibration is exactly the
  mechanism meant to absorb that difference without retuning).

- **2026-08-09 (CPU: blocked polyphase fold, float32 end to end):** Answering "should this be
  rewritten in C / ported to GNU Radio," which turned out to be a question about how the
  NumPy was written rather than about NumPy. `channelizer.py`'s fold no longer materializes
  the 24x-expanded `sliding_window_view` temporary the direct formulation needs (25 MB per
  chunk, which made the stage memory-bound rather than compute-bound); the multiply-accumulate
  is reassociated into shifted block-slices of a `(n_blocks, decimation)` view -- see that
  module's new "Blocked fold" section for the index algebra, and note the output is
  bit-identical, not merely close. Separately, precision now follows the input through
  `dc_block`, `channelizer`, `discriminator`, `audio_conditioning`, and `resample`, so
  SoapySDR's `CF32` samples stay complex64 instead of being widened to complex128 at the
  first stage; `np.fft` was swapped for `scipy.fft` because it silently upcasts complex64,
  and `lfilter`/`sosfilt`/`resample_poly` coefficients are narrowed alongside their state for
  the same reason. `Squelch.envelope()` rewritten to sum whole frames in one vectorized
  reduction and describe its output as merged constant spans, rather than making several
  NumPy calls per 2 ms frame to write a value almost always identical to the frame before it.
  Combined: channelizer 3.05x -> 17.29x real-time, full pipeline 2.04x -> 6.96x (48.9% ->
  14.4% of one core per dongle) on the sandbox benchmark. Every hazard assertion in
  `test_channelizer.py` now runs at both precisions at the *same* tolerance -- CLAUDE.md's bar
  for touching this file, met by strengthening the tests rather than by leaving them alone.
  `bench_channelizer.py` now benchmarks the full `DevicePipeline` alongside the channelizer,
  and on complex64: the channelizer alone stopped being the interesting number once it
  stopped dominating, and a complex128 benchmark measures a precision this system no longer
  runs at. See the Session Log entry this date for the full per-stage profile, the three
  silent-re-promotion traps found while narrowing, and why both rewrites are recommended
  against.

---

## Phase 2 — SAME decode end to end

**Status:** Done (2026-08-13) — live-hardware verified: a user's real RTL-SDR deployment
decoded a real over-the-air NWR Required Weekly Test (RF-sourced `Required Weekly Test`
alert visible on the dashboard, confidence 0.60, tagged `RF ONLY`), closing the one exit
criterion (roadmap.md) that stayed open through every other phase's build-order exception --
see the "Not started / open" section below, previously the blocker every later phase's
build-order note pointed back to.

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
  Not blocking Done above: the live RWT decode below proves the pipeline works end to end on
  real air, it just doesn't by itself prove this specific majority-voting assumption either
  way.

- **2026-08-13 — Live-hardware verified, closing this phase's last open item:** a user's
  real deployment decoded NWR's own Required Weekly Test off the air — exactly the "natural
  first real-world check" this section named as the way to close this gap without waiting
  for a real warning. The dashboard shows it as `Required Weekly Test`, `RF ONLY`, confidence
  0.60, tier C (`data/same_event_codes.yaml`: `RWT` is Tier C, "tests, routine programming").
  Confirms real air → `sdr-rx`'s channelizer → `same-decoder`'s multimon-ng subprocess →
  parsed `SameEvent` → `fusion` → `api` → the dashboard, all genuinely working, not just
  unit-tested against synthetic fixtures. The same session's Meshtastic dispatch question
  (see Phase 6's notes) is explained by this event's tier, not a bug: `dispatcher.service`
  gates on `TIER_A` only (`service.py` line 87), so a Tier C RWT is expected to log
  `skipped_not_tier_a` and never reach the mesh — `GET /dispatches` or
  `docker compose logs dispatcher` will show that reason for this specific event.

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

- **2026-08-09:** Audio-quality report from a live deployment (static on a marginal channel,
  occasional cutouts) led to three fixes, see the Session Log entry this date for the full
  writeup: a squelch + voice-band filter (`sdr_rx/audio_conditioning.py`) applied only to the
  `stt` ZMQ topic (never SAME decode or the ring buffer), and a bounded queue + writer thread
  in `live_audio/feeder.py` so a stalled ffmpeg-to-Icecast write can no longer block the ZMQ
  receive loop and cause silent frame drops upstream.

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
- **2026-08-09:** `nws-poller` gained optional `NWS_POLLER_ZONES` (public-forecast zone
  codes), additive to the required `NWS_POLLER_AREAS` -- one combined `zone=`-repeated
  request per cycle via a new `NwsAlertsClient.fetch_zones`, on top of the existing
  one-request-per-area calls. Building this surfaced a real duplicate-alert bug, not
  introduced by it: `Poller` tracked "seen" per request target (one `SeenAlertTracker` per
  area, plus one for the zone request), so the same CAP alert reaching both an area's
  response and the zone response -- the expected case once zones sit inside an already-polled
  area's geography -- was "new" to each tracker independently and got emitted to `fusion`
  twice. `fusion.store.AlertStore.ingest_cap` has no id-based dedup of its own to catch
  this (any `CapAlertIn` that doesn't match an open RF-only alert mints a fresh `Alert`), so
  this would have shown up as two separate rows for one real alert. Same latent issue already
  existed for two overlapping `NWS_POLLER_AREAS` (e.g. a marine warning matching both `OR`
  and `WA`) -- fixed both at once by giving `Poller` a single shared `SeenAlertTracker`
  across every area and the zone request instead of one per request target. `nws_poller`
  suite: 28 passed, up from 21.

- **2026-08-10:** Two further additions, both from the user, neither with an accompanying
  test: `nws_poller` gained `NWS_POLLER_STRICT_ZONE_FILTER` (drop a polled alert whose UGC/
  SAME codes don't hit a configured `NWS_POLLER_ZONES` entry) and `NWS_POLLER_MAX_RADIUS_MILES`
  (drop an alert whose nearest point -- from its own polygon geometry, or a small built-in
  UGC-centroid table when it has none -- is farther than that from `TOCSIN_LATITUDE`/
  `TOCSIN_LONGITUDE`; no-op unless both operator coordinates are set), applied in
  `service.py`'s `_emit_fresh` after the existing zone/area fetch and before dedup. Separately,
  `SeenAlertTracker` (`tracker.py`) now accepts a Redis client and persists its `id -> sent`
  seen-map to a Redis hash (`tocsin:nws_poller:seen`), reusing the same client `main()` already
  builds for the CAP sink -- without it, every container restart re-emitted every currently
  active alert to `fusion` as "new," since `/alerts/active` returns the full snapshot each
  poll with nothing else to distinguish "still active" from "just seen for the first time."
  In the same area, `fusion.store.AlertStore.ingest_same`/`ingest_cap` (not `nws_poller`) now
  check still-open alerts for a repeat before minting a new one -- same CAP `id`, or a SAME
  event sharing `raw_header` or `callsign`+`event_code`+`fips_codes` -- and update the existing
  `RF_ONLY`/`API_ONLY` alert in place instead of opening a duplicate (`fusion` 33 passed, up
  from 32 per the diff's added test). `API_ONLY` alert `id`s also changed from a random UUID to
  a deterministic `sha256(cap.id)[:32]`, so the same CAP alert lands on the same alert id across
  polls and process restarts, not just within one `AlertStore`'s lifetime. None of this closes
  the two deliberately-out-of-scope gaps below (a *second* SAME/CAP arrival for an
  already-`CONFIRMED` alert still opens a new Alert) -- it only dedups repeats of a still-open
  one.

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

- **2026-08-13:** A user's real deployment decoded a live NWR Required Weekly Test (Phase
  2's live-hardware verification, this date) but saw no mesh send, which surfaced a question
  rather than a bug: RWT is Tier C (`data/same_event_codes.yaml`), and `Stage1Dispatcher`
  only ever sends Tier A (`_evaluate`'s first gate, `service.py` line 87) -- worth capturing
  here since it's the natural first thing a real decode surfaces, and this section is exactly
  where "live-hardware verification is still open" was already tracked. Still true: no real
  Meshtastic node has been exercised end to end in this repo's history yet. Testing the
  actual egress path for real needs a genuine Tier A event -- either wait for a real warning
  (rare by design), or exercise `egress/meshtastic_node.py` directly against the node
  (bypassing tier gating on purpose, for a hardware-connectivity check only) rather than
  waiting on `dispatcher`'s tier gate to pass a real alert through.

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
- **2026-08-10** — Removed the Meshtastic MQTT fallback entirely, at the user's request: they
  connect only via serial/TCP node and judged the ack-fallback leg (and the node-side MQTT
  downlink config it required) not worth keeping. Deleted `egress/meshtastic_mqtt.py` and
  both its test files; `egress/dispatch.py`'s `DualPathSender` is now `MeshSender` (serial/TCP
  only, no `mode`/`mqtt_client` params); dropped the `paho-mqtt` dependency; removed
  `compose.yaml`'s `mosquitto` service, its volume, and dispatcher's `MQTT_HOST`/`MQTT_PORT`/
  `MESHTASTIC_MQTT_REGION`/`MESHTASTIC_GATEWAY_NODE_ID` env vars and `mosquitto` dependency;
  deleted `deploy/mosquitto/`; removed `MESHTASTIC_GATEWAY_NODE_ID` from `.env.example`.
  Updated `CLAUDE.md`/`AGENTS.md`'s "communicate over ZMQ, Redis, MQTT, and HTTP" line (now
  without MQTT) and every service's `heartbeat.py` docstring that quoted it. `dispatcher` 110
  passed (down from 122 -- 12 MQTT-specific tests removed, none converted, since there's
  nothing left to test). Left `data/same_event_codes.yaml`'s "Tier A: mesh + MQTT" / "Tier B:
  MQTT only" tier-naming comments alone -- that's the design doc's broader intended
  MQTT-broadcast concept for Tier B, never actually built beyond the ack-fallback leg this
  entry removes (see `service.py`'s docstring, pre-existing), so it's a separate open item,
  not something this removal touches.

**Not started / open:**
- Everything named in the three services' own READMEs as unverified: no real Meshtastic
  node, no real LiteLLM/OpenAI-compatible endpoint, no real remote STT endpoint, no real
  Redis instance, and no Docker daemon in this sandbox this session -- every wire contract in
  this phase was verified against real published specs (LiteLLM's docs, the OpenAI API shape)
  rather than guessed, but "spec-verified" isn't "live-verified."
- Tier B's general MQTT broadcast path (a design doc concept distinct from the ack-fallback
  leg removed 2026-08-10, and never built to begin with) is still unscoped in roadmap.md,
  called out again in `dispatcher/README.md`.
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

- **2026-08-09:** Live-audio playback stopped a few seconds after it started, reported from
  a running deployment. The Icecast side was fine (the source is continuous -- `sdr_rx`
  publishes a block per channel per cycle whether or not anything is on air); the UI was
  killing its own player. `renderStreams` rebuilt the whole panel with `replaceChildren` on
  every `/streams` poll, and the HTML spec requires a media element removed from the
  document to pause -- so the next 15s poll ended playback. Worse, that poll is *guaranteed*
  to carry new data for a listener, because starting playback is what increments Icecast's
  listener count. This is the same defect the 2026-08-08 session fixed for the alert feed's
  capture player; the streams panel never got the treatment. It is now a `StreamsView` that
  keeps one `<li>` and one `<audio>` per mount for the panel's lifetime, patches the header
  around them, and assigns `src` only when the URL actually changes (assigning it reloads
  the element even when the value is unchanged). `reconcile` moved from `views/alerts.ts`
  to `dom.ts` now that two views need it. A failed `/streams` poll also no longer replaces
  the list with an error banner -- the banner goes above the last known rows, since one bad
  request means the API didn't answer, not that the mounts went away. Measured in headless
  Chromium against a stub API and a chunked audio mount: before, the element was detached
  and rebuilt within the first repaint and `currentTime` never left 0; after, 25s of
  uninterrupted playback across two polls (listener count visibly advancing) on the same
  element, zero detachments.

- **2026-08-09:** `GET /reference` gained a `stations` table (`reference.py`'s
  `load_stations`) serving `data/nwr_stations_or.yaml`, with a `distance_km` per station
  (`reference.haversine_km`) computed from new `TOCSIN_LATITUDE`/`TOCSIN_LONGITUDE` config
  when both are set -- `null` otherwise, and `null` for the two stations in that file with no
  coordinates of their own, rather than a fabricated distance. `web` gained a matching
  **Nearby NWR stations** panel (`views/stations.ts`), sorted by distance when available,
  alphabetical otherwise. While building it, reworked the sidebar per live user feedback on a
  screenshot of the RF channels table: moved Spectrum to the top of the sidebar with RF
  channels directly under it (`index.html`), and rebuilt `views/health.ts` from a 6-column
  `<table>` (site/channel/RMS/trend/last-sample/status) that forced its own horizontal
  scroll into a compact dot+name+sparkline row list with an RMS/time/status detail line
  below, matching the Services/Stations panels' layout -- a wide table was a worse fit for
  the narrower sidebar position than it already was at the bottom. Verified in headless
  Chromium at 1280px and 380px against a stub API: correct panel order, distance-sorted
  station list with the coordinateless station last, dead-channel row visibly flagged, zero
  horizontal overflow at either width, no console errors beyond an intentionally-aborted
  `/events` request. `api` suite 109 passed (up from 103), `web`'s `tsc --noEmit`/`vite
  build` clean.

- **2026-08-09:** Live deployment follow-up to the `sdr-rx` CPU fix earlier this date (Phase
  1's note this date): `api` at 38.9% CPU and `postgres` at 23.9% were unexpectedly high for
  a lightweight polling REST API. Traced it to `sdr_rx.HealthTracker` publishing a Redis
  stream entry on every `sample()` call -- once per NWR channel per capture chunk, ~128/sec
  for a single seven-channel dongle -- each one round-tripping through `api`'s consumer into
  a Postgres `INSERT` and an SSE broadcast to every connected browser, for a signal whose
  only job is detecting a carrier flat for 30 continuous seconds (`FLAT_CARRIER_SECONDS`).
  Fixed at the source, not the consumer: `HealthTracker.sample()` still updates flat-carrier
  state on every call (in-process, effectively free, zero loss of detection fidelity) but
  only forwards to the sink at most once per `report_interval_s` (new parameter, default
  1.0s) per `(site, channel)` -- an ~18x cut in Redis/Postgres/SSE traffic for this stream.
  Also batched `api.redis_bus.StreamConsumer`'s per-entry `XACK` into one call per batch
  (`xreadgroup` already reads a batch in one round trip; acking one at a time threw that away
  on the write side) -- preserves the exact at-least-once/idempotent-replay semantics the
  original per-entry ack had via a `try/finally` that still acks everything that succeeded
  before a later entry's handler raised. Verified: `sdr_rx` 98 passed (up from 96, new tests
  assert reports are throttled per-channel while dead-detection timing is unaffected),
  `api` 111 passed (up from 109, new tests assert a multi-entry batch acks in one call and
  that a mid-batch failure still acks everything that completed before it). Not verified:
  the actual CPU drop on the reporting Pi -- the fix targets the mechanism the profiling
  data pointed at, not a number reproduced in this sandbox (no Postgres/Redis load-test
  harness here).

- **2026-08-10** — External-reverse-proxy readiness pass, at the user's request ahead of
  actually exposing a deployment past their LAN. Three gaps, all in the "deploy-behind-Caddy"
  half of design doc §9 that Phase 8 had deliberately left open until now:
  1. **Icecast needed its own exposed port.** The browser has always built playback URLs
     against `ICECAST_PUBLIC_URL` directly, which is fine when the reverse proxy can forward
     a second port/origin to Icecast but not when it can only forward one to `api`. Added
     `GET /stream/{mount_path}` (`app.py`): relays one mount's bytes through `api` itself via
     a streaming httpx client (`_default_open_audio_stream`, injectable for tests the same
     way `_default_http_get` already was). Deliberately opt-in, not the new default -- it
     pins one open connection per listener, the exact cost `streams.py`'s docstring already
     called out -- so it only activates when an operator sets `ICECAST_PUBLIC_URL` to a
     *relative* path (e.g. `/stream`) instead of a host; `playbackUrl` in
     `web/src/views/streams.ts` needed no change at all, since a relative `publicBase` already
     resolves correctly against the page's own origin. 4 new tests.
  2. **CORS was hardcoded to `*`.** Fine for the localhost/LAN posture this repo has shipped
     for so far, not for a deployment reachable from the internet. Added
     `CORS_ALLOWED_ORIGINS` (`config.py`, comma-separated, default `*` so nothing breaks for
     existing deployments) and wired it into `app.py`'s `CORSMiddleware`. Checked
     `SameSite` too: there's nothing to set yet, since this phase still has no auth and
     therefore no cookies -- that's a note for whenever design doc §9's "Argon2id local
     backend auth" actually gets built, not a code change now. 3 new tests.
  3. **Icecast's source/admin passwords were hardcoded `hackme` in the checked-in XML**,
     independent of the `ICECAST_SOURCE_PASSWORD` env var `live_audio` already reads --
     changing the env var alone silently broke the source auth, and there was no way to set
     the admin password via `.env` at all. Templated both into `icecast.xml` via
     `entrypoint.sh`'s existing `envsubst` mechanism (previously `ICECAST_PORT`-only), added
     `ICECAST_ADMIN_PASSWORD`, and wired both into `compose.yaml`'s `icecast` service
     environment block (it previously only received `ICECAST_PORT`).

  Also added `make db-clear-alerts` (unrelated to the proxy work, same session, user's
  request): a misconfigured `NWS_POLLER_AREAS`/`NWS_POLLER_ZONES` had populated `alerts` with
  CAP alerts for far-away areas, and there was no way to clear them short of dropping the
  whole `timescale-data` volume (which also loses `health_samples`/`transcripts`/
  `dispatches`, and re-triggers the password-lock gotcha this doc's Phase 8 notes already
  cover). `TRUNCATE`s `alerts` via `docker compose exec timescaledb psql` and restarts
  `fusion` -- both `fusion`'s `AlertStore` and `nws_poller`'s `SeenAlertTracker`
  (`tracker.py`, dedups on `(id, sent)`) are pure in-process memory with no Postgres
  read-back, confirmed by reading both, so the restart is what makes currently-valid in-area
  alerts reappear on the next poll instead of staying missing until NWS happens to reissue
  them.

  Confirmed no migration framework is needed for any of this: `db.ensure_schema` already
  applies `schema.sql` idempotently on every `api` start (CLAUDE.md/`db.py`'s own docstring:
  no Alembic/SQLAlchemy until there's a real schema-evolution story), so a future column
  would just need `ADD COLUMN IF NOT EXISTS` added to `schema.sql`, no separate migration
  step.

  Verified: `api` 118 passed (up from 115), `docker compose --profile offgrid config` and
  `make -n db-clear-alerts` both confirmed clean. Not verified: an actual external reverse
  proxy or a real Icecast container in this sandbox (no Docker daemon here) -- the `/stream`
  route is tested against a fake upstream, and `entrypoint.sh`'s `envsubst` substitution
  follows the exact pattern already proven for `ICECAST_PORT`.

- **2026-08-10 (dashboard tabs + weather map):** Web UI split into two tabs (`index.html`,
  `main.ts`) -- **Dashboard** (live audio, nearby NWR stations, a new NWS zone & weather map,
  and the alert feed on the left; spectrum, RF channels, system health, and dispatch on the
  right) and **Activity** (the merged transcript/dispatch log, plus per-service status moved
  off the Dashboard entirely, since a 5-panel sidebar next to a lone feed was the original
  layout's own known imbalance -- see the 2026-08-09 entry above). New `views/map.ts`: a
  Leaflet map on a dark CartoDB basemap (falls back to a "Vector Mode" status pill on tile
  error rather than a blank canvas) drawing only the NWS zones (`views/zone_data.ts`'s small
  hand-maintained UGC -> polygon table) currently holding an active alert, filled/outlined by
  that zone's highest active tier, plus every nearby NWR station as a tower marker colored by
  `status` with a pulsing ring on whichever station is nearest the operator, matches `KIG98`,
  or is otherwise inferred to be feeding a live channel/health sample; an optional NEXRAD
  radar overlay (Iowa State's public IEM WMS tile service) toggles on top. `data/
  nwr_stations_or.yaml` became `data/nwr_stations/`, one file per state (`or`/`wa`/`ca`/`id`
  so far); `api.reference.py` now merges every file in that directory (falling back to a
  single `nwr_stations.yaml`/`nwr_stations_or.yaml` if present, for compatibility) and reports
  `distance_miles` alongside `distance_km`. `nws_poller` gained matching geographic filtering
  (`NWS_POLLER_MAX_RADIUS_MILES`/`NWS_POLLER_STRICT_ZONE_FILTER` -- Phase 5's entry this date
  has the detail). `views/stations.ts` dropped its own distance-radius filter in favor of
  showing the full sorted list, since the map now gives a visual sense of radius instead. None
  of this shipped with new or updated `web`/`api` tests -- worth a real-browser check against
  a stub API before trusting the map/station rendering, same posture as the rest of this
  phase.

- **2026-08-10 (mobile + PWA + icon):** `app-header` now wraps instead of overflowing
  horizontally under ~900px (brand drops to its own row; nav tabs and the connection badge
  wrap together as a pair rather than the badge landing alone on a third line), and the map's
  internal Leaflet stacking context (z-index up to 1000) is isolated so it can no longer climb
  above the sticky header on scroll at that width. Added `manifest.webmanifest`, an
  `apple-touch-icon.png`, and related `<head>` tags so "Add to Home Screen" on iOS picks up
  Tocsin's own icon instead of a generated letter tile (iOS ignores SVG favicons for this).
  The Activity tab's nav-bar label was shortened from "Activity & Voice Transcripts" to
  "Activity" (the panel heading itself is unchanged) -- it was the longest label on the
  narrowest element. The favicon/app icon was also redrawn twice this date, settling on four
  layered spectrum bars with a red EKG-style pulse sweeping across them (`web/public/
  favicon.svg`, regenerated into every PNG size) -- echoes the Spectrum panel's own visual
  language instead of a literal bell, and reads cleanly down to 16px.

- **2026-08-13 (alert pruning):** `alerts` had no retention policy at all -- every alert
  `fusion` ever published stayed in Postgres forever, `GET /alerts` only ever trimmed by
  `limit`, and the web UI's `isActive()`/`expiresAt()` (`format.ts`) just kept labeling old
  rows "expired" without anything ever removing them. Surfaced by a user question after
  confirming the SAME decode path live (Phase 2, this date): how long an expired alert should
  stick around before it's gone. Added a background sweep (`api/__init__.py`'s
  `_prune_alerts_forever`, `ALERTS_PRUNE_INTERVAL_SECONDS`, default hourly) that deletes
  alerts expired more than `ALERTS_PRUNE_GRACE_SECONDS` ago (default 86400 -- one day).
  `db.alert_expiry` is a Python port of `format.ts`'s `expiresAt` (service boundary, two
  independent implementations of the same rule, CLAUDE.md) -- CAP's own `expires`/`ends` wins
  when present, falling back to the RF source's `received_at + purge_minutes`; an alert with
  no computable expiry is never pruned, same "no data means keep it" posture the web UI
  already uses. Implemented in Python rather than as a JSONB SQL expression specifically so it
  stays unit-testable without a real Postgres, which this authoring sandbox has never had. 8
  new tests in `api` (`alert_expiry`, `prune_expired_alerts`, config defaults/overrides), 128
  passing (up from 116).

**Not started / open:**
- Argon2id local backend auth (design doc §9) is still not built -- the reverse-proxy half
  of that line is now addressed (single-port exposure via `/stream`, configurable CORS,
  non-default Icecast passwords; see the 2026-08-10 entry above and the root README's new
  "Exposing Tocsin behind an external reverse proxy" section), so an operator who wants real
  auth in front of this today has to put it in the reverse proxy itself (Caddy `basicauth`,
  forward-auth, etc.).
- Not verified against a real Postgres, Redis, browser, or live upstream producer anywhere in
  this phase -- verified against fakes, fixtures, and (for `web`) a real `npm`/`tsc` run
  against the live registry, but no real page has ever been rendered against a real backend.
- `/alerts` has no pagination beyond `limit` (no cursor/offset) -- fine at current expected
  alert volumes.

**Depends on:** Phase 5 (alert store) and Phase 1 (health signal) per roadmap.md -- both
already built (Phase 5 fully proven against its own exit criteria; Phase 1 live-hardware
verified). Phase 2's real-SAME-decode gap (the last thing this note used to flag) closed
2026-08-13 -- the alert feed this UI displays has now shown a real RF-sourced alert
(`Required Weekly Test`, `RF ONLY`) end to end, not just fixtures.

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

- **2026-08-08:** Fixed `api`'s remaining restart loop, reported from a live `docker compose`
  log: `ensure_schema` died with `AttributeError: 'NoneType' object has no attribute
  'decode'` deep inside asyncpg's `_on_result__simple_query`, on every start. Not a
  connection or config problem -- `db.ensure_schema` split `schema.sql` on a bare
  `str.split(";")`, and the `dispatches` table's comment block contains a semicolon in
  prose ("Redelivery of the same stream entry can therefore double a row here; that is the
  accepted cost..."). That split the file mid-comment: the leading fragment was
  comment-only, which Postgres answers with `EmptyQueryResponse` and no command tag, so
  asyncpg had `None` to `.decode()` -- hence a `AttributeError` rather than any SQL error
  in the traceback (confirmed against asyncpg 0.31.0's `coreproto.pyx`, which discards `I`
  messages and leaves `result_status_msg` unset). The trailing fragment started mid-comment
  and would have been a syntax error, so `dispatches` and its two indexes were never
  created on any deployment that got this far. Replaced the split with `_split_statements`,
  a scanner that skips `--` comments, nested `/* */` blocks, and quoted literals before
  splitting -- deliberately no dollar-quote handling, since `schema.sql` is plain DDL with
  no function bodies and a future `$$` block would fail loudly as a syntax error rather
  than silently. The prose semicolon stays in `schema.sql` on purpose, as the regression
  fixture. Tests: comment-semicolon and literal/block-comment cases, plus one that parses
  the real checked-in `schema.sql` and asserts every fragment starts with `CREATE`/`SELECT`
  and that `dispatches` survives. `api` suite 103 passed. Not verified: a real `up` against
  a live Postgres -- still no Docker daemon in this sandbox.

- **2026-08-08:** Four bugs reported from a live hybrid deployment with screenshots: the
  alert feed rendering as a stack of blank lines and flashing constantly, `stt-worker` and
  `nws-poller` both showing "no heartbeat", and the spectrum panel looking wrong.
  1. **Feed of blank lines.** Not a data problem -- 123 real API_ONLY alerts were being
     rendered, then squashed. `.alert-feed` is a flex column with `max-height: 62vh`, and
     `.alert-card`'s `overflow: hidden` (there for the rounded corners) zeroes a flex
     item's *automatic minimum size*, so once the feed held more alerts than fit, every
     card shrank to a ~5px sliver with its content clipped. Measured in a headless
     Chromium against a stub API: 118.25px per card with `flex-shrink: 0`, 4.97px without.
  2. **Flashing.** `Store.notify()` repainted every panel on every change, and `health`
     delivers one SSE sample per channel per second (seven channels here), so the entire
     alert feed was torn down and rebuilt ~10x/second -- which also dropped its scroll
     position and stopped any capture mid-playback. Changes now declare a topic and
     listeners get the set that changed; `AlertFeedView` additionally reuses each card
     unless its rendered content would differ (signature includes the two clock-derived
     strings) and patches the list in place. Measured: 0 DOM mutations under `#alerts`
     over 10s of live health SSE, against ~1200 node rebuilds/s before.
  3. **Paging.** There was none -- the feed built every alert it held. Now 40 at a time
     with a "show more" button, reset when a filter changes. A scrolling log wants
     incremental reveal, not numbered pages.
  4. **`stt-worker`: no heartbeat.** The deployment transcribes against a remote endpoint
     and never staged a ggml model, but `main()` blocked in `await_model` before the
     heartbeat loop -- forever, for a file that was never coming. `STT_CHAIN` now accepts
     `remote` with no `local`: no model required, no wait, and every tier goes remote
     (Tier B's local-only rule exists to prefer a free local provider; there isn't one).
     `await_model` also beats while waiting, so a genuinely-waiting worker is
     distinguishable from a crashed one. Unrelated but adjacent: `handle_capture` failures
     no longer kill the loop and drop every later capture.
  5. **`nws-poller`: no heartbeat.** A healthy poller flapping. The heartbeat key's TTL is
     30s and it beat once per poll cycle, which defaults to 60s -- so the key was expired
     for half of every cycle. It now sleeps in 5s slices and beats in each one.
  6. **Spectrum.** Three things: the channel axis carried NOAA/scanner numbering
     (WX1=162.550) while the rest of the system uses design doc §3's ascending numbering,
     so the axis read "WX2 WX4 WX5 WX3 WX6 WX7 WX1" left to right; the canvas backing
     store stayed at its 640x260 attributes while laid out at `width: 100%`, so the image
     was stretched; and the hardcoded -110..-20 dB window doesn't fit uncalibrated
     channelizer magnitudes, which bunched every bin into one flat yellow wash. Fixed the
     numbering against `channels.py`, sized the canvas to its box times the device pixel
     ratio, and replaced the fixed window with a smoothed percentile range over the
     retained history (still one scale for every row on screen -- the property a per-frame
     min/max lacked -- with the actual dB numbers drawn on the axis).

  Verified: `stt_worker` 49 passed, `nws_poller` 21 passed, `tsc --noEmit` and `vite build`
  clean, and the four UI claims measured in headless Chromium against a stub `api` serving
  123 API_ONLY alerts and a live health SSE stream. Not verified: a real `up` -- still no
  Docker daemon in this sandbox, so the remote-only STT path and the poller's heartbeat
  cadence are covered by unit tests with injected clocks/heartbeats rather than observed.

- **2026-08-09:** Live weather-feed playback stopped a few seconds after starting, reported
  from a running deployment. The streams panel rebuilt its `<audio>` elements on every 15s
  `/streams` poll, and a media element removed from the document is paused by the browser
  per spec — the same tear-down the alert feed's capture player was fixed for on 2026-08-08.
  `renderStreams` is now `StreamsView`, holding one row and one player per mount across
  repaints, and a failed poll leaves the list (and any playing audio) in place instead of
  replacing it with an error banner. Verified in headless Chromium against a stub API
  serving a continuous audio mount: 25s of uninterrupted playback across two polls on the
  same element, against a pre-fix build that lost it inside the first repaint.

- **2026-08-09 (later same day):** NWR Oregon station data, added earlier this date as a
  plain reference file, extended and wired end to end: `data/nwr_stations_or.yaml` gained
  `power_watts`/`lat`/`lon` per station (two left `null` -- no coordinates found anywhere,
  see Phase 0's entry this date); `api` gained `TOCSIN_LATITUDE`/`TOCSIN_LONGITUDE` config
  and a `stations` table on `GET /reference` with a haversine `distance_km` per station
  (`null` when the operator location or the station's own coordinates are unset -- never
  fabricated); `web` gained a **Nearby NWR stations** panel, sorted by distance. Building
  the panel led to a live-feedback sidebar rework (user request against a screenshot of the
  RF channels table): Spectrum moved to the top of the sidebar with RF channels directly
  under it, and RF channels itself was rebuilt from a 6-column table into a compact row list
  matching the Services/Stations panels, since the table forced horizontal scroll even
  before the reorder and would have been worse squeezed under the waterfall. Separately,
  extending `nws_poller` with optional `NWS_POLLER_ZONES` (additive to `NWS_POLLER_AREAS`,
  per a Vertex-project config the user referenced) surfaced a real pre-existing bug: `Poller`
  tracked "seen" alerts per request target, so the same CAP alert reaching two overlapping
  request targets (which zones nested inside an area's geography make the common case, not
  an edge case) was emitted to `fusion` twice -- and `fusion.store.ingest_cap` has no
  id-based dedup to catch it, so this would have surfaced as duplicate alert rows. Fixed with
  one `SeenAlertTracker` shared across every area and the zone request instead of one per
  target; this also silently fixes the pre-existing two-overlapping-areas case (e.g. a marine
  warning matching both `OR` and `WA`). Verified: `api` 109 passed (up from 103), `nws_poller`
  28 passed (up from 21), `web`'s `tsc --noEmit`/`vite build` clean, and headless Chromium at
  1280px/380px against a stub API -- correct panel order, distance-sorted station list with
  the coordinateless station last, dead-channel row flagged, zero horizontal overflow either
  width, no unexpected console errors. Not verified: a real `up` against a live Postgres/
  Redis/`api.weather.gov` -- still no Docker daemon or outbound access to those specific
  hosts confirmed in this sandbox.

- **2026-08-09 (follow-up):** Layout feedback against a screenshot of the merged PR running
  live (real `TOCSIN_LATITUDE`/`TOCSIN_LONGITUDE` configured -- the RF/distance numbers in the
  screenshot were real, not stub data): RF channels' single-column row list wasted most of the
  panel's width on seven short rows, and Nearby NWR stations, sorted correctly, still read as
  one long scroll for 25 entries. Both reworked into card grids. RF channels (`health.ts`)
  became `.health-grid`, auto-fit columns (usually 2, sometimes 1 on a narrow phone) since it
  stayed in the narrower right sidebar; the sparkline's fixed 72px width became `100%` with
  `preserveAspectRatio="none"` so it stretches to whatever the card ends up. Nearby NWR
  stations moved to the wider left column (under Live audio) and became `StationsView`, a
  class rather than a render function -- the only panel here besides `WaterfallView`/
  `StreamsView` that needs to remember state across repaints, in this case which page it's on.
  Fixed 3 columns x 2 rows (6/page) with Prev/Next, per explicit direction to cap it and page
  through the rest rather than scroll or "show more" -- `.station-grid` falls back to
  `auto-fit` under 560px so 3 fixed columns don't get crushed on a phone (the existing 900px
  breakpoint only collapses the two-column *page* layout, not a panel's own internal grid).
  Verified in headless Chromium at 1400px and 380px against a stub API seeded with all 25 real
  station names (page 1 -> Next -> page 2, "Page 2 of 5", 6 cards, correct entries both before
  and after the resize to mobile -- pagination state survives a viewport change since it's the
  same view instance): zero horizontal overflow either width, no unexpected console errors.
  `npm run build` clean. No Python changed this round.

- **2026-08-09 (later same day):** User feedback against the live PDX site: static on a
  marginal channel and occasional audio cutouts on the Icecast live-audio stream, plus a
  question about whether the default 30 dB gain was too high. Root-caused two independent
  issues rather than one:
  1. **Static** was the FM discriminator's raw phase output streaming unfiltered -- no
     squelch, no band-limiting -- so any dip below FM capture threshold passed through as
     full-scale noise, hard-clipped by `to_s16le`'s `[-1, 1]` clamp on top of that. New
     `sdr_rx/audio_conditioning.py`: `VoiceBandFilter` (streaming Butterworth bandpass,
     ~300 Hz-3 kHz, NWR's voice bandwidth) and `Squelch` (noise gate keyed on energy above
     8 kHz -- the classic FM "noise triangle" proxy for no-carrier, since level alone can't
     tell a strong carrier's floor from a weak one -- with hang time and a short crossfade so
     the gate doesn't chatter or click). Threshold (`SQUELCH_DEFAULT_THRESHOLD = 0.6`) picked
     from synthetic no-carrier-vs-carrier discriminator output (~1.5-1.8 vs. ~0.04-0.4 RMS in
     the noise band, see the module docstring and its tests), configurable per site via
     `SDR_RX_SQUELCH_THRESHOLD` -- same "starting point, not universal" posture as gain.
     Wired into `pipeline.py` on the `stt` topic publish **only**: SAME decode and the ring
     buffer `segment_capture` reads alert audio from both stay on the raw, unfiltered
     discriminator output, since a misfiring gate must never be able to eat a real SAME header
     or clip a warning clip. `test_pipeline.py` gained a regression test asserting exactly
     that split (forced-closed squelch silences `stt` while `same` stays untouched).
  2. **Cutouts** turned out to be architectural, not RF: `live_audio`'s `main()` loop is
     single-threaded (`subscriber.recv()` -> `streamer.feed()` -> `feeder.write()` in
     lockstep), and `write()` was a blocking `stdin.write()` to ffmpeg. A network stall
     between ffmpeg and Icecast blocked that write, which stalled the whole loop, which
     stopped draining the ZMQ SUB socket -- whose receive buffer then silently dropped frames
     once its HWM filled (`subscriber.py`'s deliberate drop-under-load policy, meant for
     genuine overload, not a downstream network blip). Fixed in `feeder.py`: `write()` now
     pushes onto a small bounded queue (`DEFAULT_QUEUE_MAXSIZE = 40`, ~2s of audio) drained by
     a dedicated writer thread that owns the actual blocking call; once full, the oldest
     buffered chunk is dropped for the newest. `close()` reworked to match: join the writer
     briefly first (the common case drains and exits cleanly), only force-terminating ffmpeg
     early if the writer is actually stuck mid-write.
  3. **Gain** wasn't changed in code -- 30 dB is a per-site starting point already documented
     as such (`capture.DEFAULT_GAIN_DB`, `SDR_RX_GAIN_DB`), not a bug, and it's one dongle
     shared across all seven channels so it can't be tuned per-channel; answered by pointing
     at the existing `SDR_RX_GAIN_DB` knob and explaining the FM threshold effect rather than
     touching anything.

  Verified: `sdr_rx` 93 passed (up from 92, +1 net given the new `audio_conditioning.py` test
  module counted in both the before/after comparison -- see the new tests themselves for the
  synthetic-signal validation of the squelch/filter behavior), `live_audio` 34 passed (up from
  33). Not verified: real hardware -- no RTL-SDR, ffmpeg, or Icecast available in this sandbox,
  same standing limitation as the rest of Phase 1/3; the actual static/cutout improvement is
  unconfirmed against a live signal until a user reports back.

- **2026-08-09 (stt-worker remote logging):** Reported from a live hybrid deployment: every
  `STT_CHAIN=local,remote` transcription was failing against the remote endpoint (a gRPC-backed
  self-hosted whisper server, per the reported error shape -- `rpc error: ... ffmpeg ... Invalid
  data found when processing input`, immediate/sub-200ms failures consistent with the remote
  backend rejecting every upload before ever reaching the model), but nothing in `stt-worker`'s
  own logs said so -- the only place it showed up was that remote backend's own request-log UI.
  Root cause of the *invisibility* (not the remote backend's own decode failure, which is
  external infrastructure outside this repo): `service.py`'s `_transcribe` race deliberately
  swallows any remote exception/timeout to fall back to local (design doc §6 -- "a remote hiccup
  degrades quality, never availability"), but did so with a bare `except Exception: return
  local_transcript` and no logging at all, so a remote endpoint that fails on literally every
  capture was silently indistinguishable from one working fine and simply losing the race. Added
  a `stt-worker: remote STT failed, using local result instead: ...` stderr log at that catch
  site (`docker compose logs stt-worker` now surfaces it) without changing the fallback behavior
  itself. 2 new tests (`test_remote_failure_is_logged_not_silent`,
  `test_remote_timeout_is_logged_not_silent`) plus README's Status section documents the log
  line; 51 `stt_worker` tests passing. Did not change `remote_http.py`'s request shape (multipart
  `file`/`model` fields, filename/content-type both already correctly `.wav`/`audio/wav`) since
  nothing in this repo's client code reproduces the remote server's decode failure -- that half
  is the operator's remote endpoint to fix or reconfigure, now that it's actually visible.

- **2026-08-09 (follow-up, actual root cause found):** The user reported the same host+model
  works fine through `d3mocide/Vertex` (a sibling project, also self-hosted, also transcribing
  against this same remote whisper backend) and asked what's different -- which turned "the
  remote backend is broken" from an assumption into a falsifiable question, since the previous
  entry's guess (nothing wrong with `remote_http.py`'s request shape) was wrong. Cloned Vertex
  and traced its actual remote-STT path (`transcription/main.py`): it calls
  `litellm.atranscription(file=(path.name, audio_bytes), ...)` -- a 2-tuple with no explicit
  content-type, which routes through the `openai` SDK's `_transform_file` into `httpx`'s
  `FileField._guess_content_type`, which calls `mimetypes.guess_type(filename)`. Verified directly
  (installed both packages, read the source, ran it): for a `.wav` filename this resolves to
  `audio/x-wav`, not `audio/wav`. `remote_http.py` was hardcoding the literal string `"audio/wav"`
  in the multipart file tuple's content-type slot -- so the previous entry's "already correctly
  `.wav`/`audio/wav`" was the bug itself, not evidence against one. A self-hosted whisper backend
  that keys its upload-format detection off the declared Content-Type, doesn't recognize
  `"audio/wav"` specifically, and falls back to assuming mp3 explains every observed symptom at
  once: the `.mp3`-named temp file in the original error, the ffmpeg demuxer failure on genuinely
  valid WAV bytes, and the 100%/every-single-request failure rate (deterministic on a header
  string, independent of audio content). Fixed by deriving the content-type via
  `mimetypes.guess_type` (matching httpx's own logic) instead of a hardcoded literal. 1 new
  regression test (`test_run_sends_mimetypes_guessed_content_type_for_wav`); 52 `stt_worker` tests
  passing. Not verified against the actual remote backend (no access to it from this sandbox) --
  the fix is confirmed correct by tracing both SDKs' real source down to the exact
  `mimetypes.guess_type` call and its output on this filename pattern, not by reproducing the
  failure against the live host.

- **2026-08-09 (later same day):** Follow-up from a screenshot of `htop` on the live deployment
  after merging the squelch/filter/buffering PR above: `sdr-rx` pegged at 99.7% CPU on one core,
  load average pushing 3 on what looks like a 4-core box, and cutouts still happening. Rather
  than guess whether the new squelch/filter code was the cause, profiled
  `DevicePipeline.process()` with `cProfile` against a synthetic full-rate chunk (65,536 IQ
  samples, the real `capture.DEFAULT_CHUNK_SIZE`) and a null publisher/tmpdir ring buffer, to
  isolate CPU cost from I/O. First checked whether the squelch/voice-filter added this session
  was the culprit: stubbing both out dropped per-chunk time from 38.73ms to 35.90ms -- real
  (~8%) but not the dominant cost, and the pipeline was already only at a 1.41x-1.52x real-time
  margin *before* today's changes even entered the picture. `bench_channelizer.py` (channelizer
  alone) measured 2.44x on this same sandbox -- so more than half the full pipeline's cost was
  coming from outside the channelizer itself.

  `cProfile` sorted by cumulative time named the actual dominant cost immediately:
  `scipy.signal.resample_poly` (2,800 calls, 4.145s of an 8.302s total across 200 iterations),
  almost entirely inside `firwin`/`get_window`/`kaiser` -- i.e. **filter design**, not the
  actual resampling math. `resample.py` calls `resample_poly(audio, up, down)` with `up`/`down`
  fixed per call site (441/1000 for the SAME-decode rate, 8/25 for STT/live-audio), but left at
  its defaults `resample_poly` *redesigns* its anti-aliasing FIR filter from scratch on every
  single call -- confirmed by reading its source (`scipy==1.17.1`): if `window` is array-like
  it's used as literal filter taps and the design step is skipped entirely, matching a
  documented (if not fully public-API) code path. Replicated its internal design formula
  (`half_len = 10 * max(up, down)`, `firwin(2*half_len+1, 1/max(up,down), window=('kaiser',
  5.0))` after reducing `up`/`down` by their gcd) in a new `_resample_poly_filter()`, cached with
  `functools.lru_cache`, and passed back in via `window=`. Verified numerically identical to
  the uncached default output for both ratios (`test_resample.py`'s two new tests) rather than
  trusting the formula-replication by inspection alone -- if a future scipy version changes its
  default heuristic, those tests fail loudly instead of silently changing the resampled audio.
  This alone took per-chunk time from 38.73ms to 24.79ms (1.41x -> 2.20x real-time margin).

  Re-profiling after that fix surfaced two more, smaller items. `ring_buffer.py`'s `write()`
  called `self._mmap.flush()` on every chunk (~0.4ms/call x 7 channels/chunk); the ring buffer's
  own docstring says it's meant to live on tmpfs, and `flush()`/msync exists to persist dirty
  pages to a *backing store*, which tmpfs doesn't have -- cross-process visibility for a
  `MAP_SHARED` mapping of the same file doesn't depend on it. Verified this empirically first
  (two independent `np.memmap` instances on the same file, writer never flushing, reader seeing
  writes immediately either way) before removing the call from the hot path (kept in `close()`
  for a clean shutdown), and added a regression test using a second, independent mmap to stand
  in for `segment_capture`'s actual reader process. `channelizer.py`'s `_demodulate()` called
  `np.exp()` on a full chunk's worth of samples (65,536) every call, but the modulation ramp is
  periodic with period `2 * num_bins` = 96 -- only 96 distinct values ever occur. Replaced with
  a precomputed 96-entry lookup table gathered by index (`(sample_index + arange(n)) %
  mod_period`), leaving `test_channelizer.py`'s strict swept-tone amplitude/phase/chunk-boundary
  assertions completely unmodified per CLAUDE.md's bar for this file -- all 21 still pass. Final:
  17.73ms -> 15.86ms per chunk (3.08x -> 3.44x).

  Net result: 38.73ms -> 15.86ms per chunk, a ~2.4x throughput improvement, all three fixes
  behavior-preserving (verified against existing tests plus new targeted regression tests, not
  just "it still passes"). Verified: `sdr_rx` 96 passed (up from 93). Not verified: the actual
  Pi this was reported against -- this sandbox's per-core speed relative to a Pi 5 is unknown,
  so the *ratio* of improvement is the number to trust here, not the absolute real-time factor;
  whether 3.44x-on-this-sandbox is comfortably above or still uncomfortably close to 1.0x on the
  real hardware is an open question until measured there directly (`make bench-channelizer`,
  or better, timing the real `DevicePipeline.process()` loop against a live dongle).

- **2026-08-09 (later same day):** Follow-up screenshots from the same live deployment, before
  vs. after merging the `sdr-rx` CPU PR: `sdr-rx` now sits around 85-88% of one core (both its
  threads combined) instead of pegged at 99.7% -- consistent with roughly the 1.17x-1.2x
  real-time margin the earlier sandbox numbers predicted once corrected for a Pi core being
  slower than the sandbox's, up from an estimated well-under-1.0x before that fix (matching the
  original "pegged solid, buffering broken" report). But the user's real question was about the
  *aggregate* jump: all four cores at 84-91% with `api` at 38.9% and `postgres` at 23.9%, on a
  Pi that also runs an independent ADS-B feeder (`readsb`) and a P25 trunked-scanner stack
  (`op25`/`liquidsoap`) against other SDRs, unrelated to Tocsin. First worth ruling out: the
  screenshot showed two rows each for `sdr-rx`, `live_audio`, `same_decoder`, and
  `segment_capture` -- not duplicate containers (a real concern, would mean a bad redeploy):
  every pair had byte-identical VIRT/RES/SHR, the signature of two *threads* of one process
  (sdr-rx's capture thread + its mostly-idle main loop; libzmq's background I/O thread for the
  other three), not two separate processes.

  Root-caused the actual `api`/`postgres` cost by reading `sdr_rx.health`, `api.redis_bus`, and
  `api.ingest` together rather than profiling blind: `HealthTracker.sample()` is called once
  per NWR channel per capture chunk in `DevicePipeline.process()` -- seven times every ~55ms,
  ~128/sec for one dongle -- and every call unconditionally published to the `tocsin:health`
  Redis stream. `api`'s consumer reads that stream in batches of up to 100 but then processed
  each entry with its own individual Postgres `INSERT` *and* its own individual SSE broadcast to
  every connected browser, sequentially, awaited one at a time. None of that per-chunk
  granularity serves the signal's actual purpose -- `FLAT_CARRIER_SECONDS = 30.0`, detecting a
  channel dead for 30 continuous seconds -- so fixed it at the source rather than patching the
  consumer's batching alone: `HealthTracker` now throttles how often it forwards to the sink
  (default once per second per channel, `report_interval_s`) while still updating its internal
  flat-carrier timer on every call, so dead-channel detection timing is provably unaffected (new
  test drives it through the full 30s boundary on the *unthrottled* per-chunk cadence and
  confirms `dead` still flips at the right instant). This alone is an ~18x cut in Redis
  XADDs/Postgres inserts/SSE broadcasts for this one stream. Also batched `api.redis_bus`'s
  per-entry `XACK` into one call per batch, since `xreadgroup` already reads a batch in a single
  round trip and acking it back one entry at a time threw that away -- done via a `try/finally`
  so a handler that raises partway through a batch still acks everything that completed before
  it, preserving the exact at-least-once semantics the original per-entry ack had (two new
  tests: one asserting a 3-entry batch acks in a single call, one asserting a mid-batch failure
  still acks the entries that succeeded before it).

  Separately, the user pointed at `d3mocide/op25-downstream` (a GNU Radio-based P25 decoder,
  also streaming to Icecast) asking whether it has transferable optimizations. Cloned and read
  it rather than assuming: its DSP core is GNU Radio -- compiled C++ blocks with VOLK SIMD
  kernels, not Python/NumPy -- which is a different, and faster, execution model than Tocsin's
  channelizer, but adopting it would mean rewriting `sdr_rx`'s signal chain onto a different
  framework entirely, not a portable optimization; out of scope here and flagged as a real
  architecture decision rather than attempted piecemeal. Its Icecast path (`liquidsoap` instead
  of `live_audio`'s `ffmpeg` subprocess) isn't a lead either -- `live_audio` measured at ~5% CPU
  total in the same htop capture, not a hot spot, so there's no profiling evidence a swap would
  help. The one genuinely useful find: `squelch_core.py`'s noise squelch (credited to PA3FWM/
  DB1NV) is a materially more sophisticated design than `sdr_rx.audio_conditioning.Squelch` --
  self-calibrating against a rise-only-tracked no-carrier reference (dB-of-quieting, no
  per-site threshold hunting, directly answering the "how do I pick `SDR_RX_SQUELCH_THRESHOLD`"
  question left open in the squelch PR) with a proper 4-state attack/hang/rehold machine to
  avoid chatter at the threshold. Worth a follow-up quality pass on the squelch itself; it is
  not a CPU fix (if anything slightly more compute than the current version) so left for a
  separate task rather than folded into this one.

  Verified: `sdr_rx` 98 passed (up from 96), `api` 111 passed (up from 109). Not verified: the
  actual CPU numbers on the reporting Pi after this fix -- no way to reproduce Postgres/Redis
  load at that rate in this sandbox, so this is confirmed by tracing the exact call path and
  its frequency, not by reproducing the observed CPU drop directly.

- **2026-08-09 (squelch upgrade + GNU Radio question):** Two follow-ups from the same
  conversation. First, whether `sdr_rx` should be rewritten on GNU Radio (op25-downstream's
  own foundation) rather than the custom NumPy/SciPy channelizer. Answered without
  implementing anything: op25 being faster is expected (compiled C++ blocks with VOLK SIMD
  kernels vs. Python/NumPy is a genuinely different execution model) but not new information,
  and porting `sdr_rx`'s core would mean re-deriving and re-verifying every hazard CLAUDE.md
  calls out (odd-stacked phase correction, batched FFT, DC-blocking order) inside a
  flowgraph model that's substantially harder to unit-test at the granularity
  `test_channelizer.py` currently achieves with pure synthetic NumPy arrays and no hardware.
  Recommended against it for now: the CPU problem this session already turned from "falling
  behind" into "thin but real margin" (the two PRs above), which changes the cost/benefit of
  a full rewrite considerably from where it stood before those fixes landed. Flagged as a real
  v2 architecture decision to revisit later if headroom is still a problem after squeezing
  what's left in the current approach, not something to fold into an optimization pass.

  Second, porting op25-downstream's noise squelch (`squelch_core.py`) into
  `sdr_rx.audio_conditioning.Squelch`, replacing its fixed-RMS-threshold design -- see Phase
  1's note this date for the technical writeup (self-calibrating reference, dB-relative
  thresholds, the 4-state hysteresis machine, the two real bugs found and fixed while
  calibrating and testing against this system's actual channelizer chain rather than trusting
  the port by inspection). Config env var renamed `SDR_RX_SQUELCH_THRESHOLD` ->
  `SDR_RX_SQUELCH_OPEN_DB` to match (`README.md`, `pipeline.py`, `__init__.py`,
  `test_pipeline.py`'s force-closed test updated to the new dB semantics). Verified: `sdr_rx`
  102 passed (up from 96). Not verified: real hardware -- calibrated against this system's own
  simulated DC-block/PFB/discriminator chain, not a live dongle's actual noise floor.

- **2026-08-09 (sdr_rx CPU: blocked polyphase fold + float32 end to end)** — The user asked
  whether `sdr_rx` should be rewritten in C or ported to GNU Radio, given how CPU-intensive
  the container is. Profiled `DevicePipeline.process()` per stage before answering (the
  earlier entries this date fixed three *incidental* inefficiencies -- a redesigned resample
  filter, an mmap flush, a transcendental in the demod ramp -- without ever touching the
  channelizer's own arithmetic). Per-stage, on the dev sandbox at the design's 1.2 MS/s /
  65,536-sample chunk: channelizer 9.39 ms/chunk (64% of the pipeline), squelch 1.61 ms
  (11%), DC block 1.02 ms, the two resamplers 1.46 ms, voice filter 0.49 ms, everything else
  under 0.4 ms combined. So the answer to "rewrite in another language" turned on one
  question: how much of that 64% was the algorithm's actual arithmetic, and how much was the
  way it had been written in NumPy.

  Almost all of it was the way it had been written. Two things, neither requiring a new
  language:

  - **The fold was memory-bound on a temporary it did not need.** `sliding_window_view` +
    multiply + `reshape(...).sum(axis=1)` expands the input by `num_taps / decimation` = 24x
    into a 25 MB intermediate per chunk before summing it straight back down. Reassociating
    the multiply-accumulate (see `channelizer.py`'s new "Blocked fold" section for the index
    algebra: `f*D + t*M + q*D + m0 == (f + t*R + q)*D + m0`) turns the whole fold into
    `R * taps_per_bin` = 24 shifted block-slices of a `(n_blocks, decimation)` view, each
    scaled by one row of the prototype and accumulated in place, with no expansion and each
    step staying in cache. Same arithmetic, same summation order, **bit-identical** output --
    asserted with `assert_array_equal` against the direct windowed form, not a tolerance,
    since a reassociation that only agreed to within rounding would mean the order had drifted.
  - **Nothing in the chain had any business being float64.** `capture.py` already asks
    SoapySDR for `SOAPY_SDR_CF32`, and the source is an 8-bit ADC; every stage was then
    widening that to complex128 on the way in (`np.asarray(x, dtype=complex)`), doubling the
    traffic through the bandwidth-bound fold for ~96 dB of headroom over an ADC that offers
    ~48. Precision now follows the input through `dc_block`, `channelizer`, `discriminator`,
    `audio_conditioning`, and `resample`. Three traps found doing this, each of which would
    have silently re-promoted the stream and produced a no-op: `np.fft` upcasts complex64 to
    complex128 (switched to `scipy.fft`, which does not); `lfilter`/`sosfilt` take their
    working type from the widest of signal, coefficients, and `zi`, so float64 taps alone
    re-promote a float32 signal (coefficients and state now narrowed alongside); and
    `resample_poly`'s window taps do the same (now cached per dtype).

  Also rewrote `Squelch.envelope()`, the next item down. Its per-frame Python loop made
  several NumPy calls per 2 ms frame -- 27 frames per chunk per channel, 7 channels -- to
  write a gain value almost always identical to the frame before it. It now sums all whole
  frames in one vectorized reduction, runs the state machine on scalars, and *describes* the
  envelope as merged constant spans plus the occasional ramp (with a closed form for the
  ramp endpoint, exact because the ramp is monotonic) rather than materializing it frame by
  frame. Bit-identical to the direct form, verified against a transcription of the previous
  implementation driven with chunk sizes coprime to the frame length.

  Measured, same box, same benchmark, before vs after: **channelizer 3.05x -> 17.29x**
  real-time (32.8% -> 5.8% of one core per dongle), **full pipeline 2.04x -> 6.96x** (48.9%
  -> 14.4% of one core per dongle) -- 3.4x end to end, on top of the ~2.4x from the earlier
  entry this date. `bench_channelizer.py` now reports both figures and runs on complex64,
  since it was measuring a precision the system no longer runs at; the channelizer alone
  stopped being the interesting number once it stopped dominating.

  So: **recommended against both the C rewrite and the GNU Radio port**, more firmly than the
  earlier entry this date did, and for a better reason than "the cost/benefit changed." The
  arithmetic was never the problem -- 28.8M complex MACs/sec for the fold is nothing, and
  NumPy already runs it in vectorized C. What cost 64% of the pipeline was a 24x memory
  expansion and a 2x-too-wide sample type, both of which are Python-level authoring choices
  that a rewrite would have "fixed" only incidentally, while re-deriving every hazard
  CLAUDE.md calls out inside a framework that is much harder to unit-test at
  `test_channelizer.py`'s granularity. The remaining profile is flat (channelizer 2.9 ms,
  squelch 0.9 ms, resamplers 1.4 ms, DC block 0.85 ms) with no single dominant stage left,
  which is the point at which a language change would start to be the honest answer -- but at
  14.4% of a core per dongle there is nothing left to buy.

  Verified: `sdr_rx` 124 passed (up from 102) -- the swept-tone amplitude, phase-stability,
  bin-leakage, and chunk-invariance hazard tests are now parametrized over both precisions at
  the *same* tolerances, not looser ones for float32 (measured: amplitude std <= 6e-8, phase
  drift <= 2.8e-8, far-bin leakage <= 8.2e-7 against bars of 1e-6/1e-6/1e-3); plus new tests
  for the blocked fold's bit-equality, the squelch spans' bit-equality, and dtype propagation
  through every narrowed stage. `same_decoder` 29, `live_audio` 34, `segment_capture` 48 all
  still pass. Additionally checked outside the suite: the complex128 path is bit-identical to
  the pre-change implementation across ragged chunk boundaries, and the actual published PCM
  for both ZMQ feeds, driven by a synthetic 1 kHz-tone-on-WX5 FM signal, differs by at most 1
  LSB (0.009% of signal rms -- s16 quantization, not a signal change) with the recovered tone
  still at 999.5/999.6 Hz. Not verified: real hardware, or the CPU numbers on the reporting
  Pi -- a Pi core is roughly 3-4x slower than this sandbox's, which is consistent with the
  pre-fix pipeline (48.9% here) being reported as pegged there, but that scaling is inferred,
  not measured.
- **2026-08-09 (squelch env wiring + per-channel live-audio gating)** — Two follow-ups from
  the user tuning a real deployment after the CPU-cut entry above. First, a bug: `sdr_rx`
  already read `SDR_RX_SQUELCH_OPEN_DB` from the environment (added with the squelch itself,
  the entry above's predecessor), but `compose.yaml`'s `sdr-rx` service never forwarded it
  into the container the way it does `SDR_RX_GAIN_DB` -- so setting it in `.env` silently did
  nothing. Wired it through `compose.yaml` and documented it in `.env.example` next to gain
  (previously only in `services/sdr_rx/README.md`'s config table).

  Second, an optimization: the user noticed one channel (WX7) never producing audio and asked
  whether monitoring all seven NWR channels at once was itself a real CPU cost worth cutting
  for a deployment that only has usable signal on one or two. Traced it to `live_audio`'s
  `Streamer.feed()` (`service.py`): a channel gets its ffmpeg/vorbis encoder and Icecast
  source connection lazily on first audio, but "lazily" only means "on first message ever
  received" -- since sdr-rx publishes all seven channels continuously, every deployment ran
  seven permanent ffmpeg processes regardless of whether 0 or 7 people were listening (visible
  in the user's `htop` output as seven always-on `ffmpeg -c:a libvorbis` processes). The
  channelizer itself was left alone -- it captures the whole 162.400-162.550 MHz band in one
  PFB pass regardless of channel count, and narrowing capture would mean losing SAME/alert
  decode on the other channels entirely, the actual safety feature this project exists for.
  Added `LIVE_AUDIO_CHANNELS`, a comma-separated allowlist (`Streamer.__init__`'s new
  `allowed_channels: frozenset[str] | None`, gated at the top of `feed()` before a feeder is
  ever created) -- empty/unset streams every channel, same as before this existed, matching
  `NWS_POLLER_ZONES`'s "optional, additive-or-absent" env-var shape rather than requiring the
  full `WX1..WX7` list up front. Deliberately not filtered at the ZMQ subscribe level or
  inside sdr-rx: SAME decode and the alert ring buffer are sdr-rx's other two consumers of the
  same per-channel audio and must keep watching every channel regardless of what a listener
  cares about -- the gate only ever narrows what `live_audio` itself does with a channel it
  still receives.

  Verified: `live_audio` 37 passed (up from 34) -- three new cases cover a channel outside the
  allowlist never spawning a feeder or appearing in `mounts()`, one inside it streaming
  normally, and `None` (no allowlist) still streaming every channel unchanged. `sdr_rx`
  `test_main.py` 3 passed for the compose/env fix. Not verified: real hardware -- ffmpeg and a
  live Icecast server aren't available in this sandbox, consistent with this module's existing
  "Status" note in `services/live_audio/README.md`.

  Follow-up, same session: asked whether `live_audio` gating unwanted channels was worth
  extending into `sdr_rx` itself, since `DevicePipeline.process()` still ran voice-filter,
  squelch, resampling, and s16 encoding for all seven channels every chunk regardless of
  `LIVE_AUDIO_CHANNELS` -- `live_audio`'s gate just discarded the result. Revisits the "not
  filtered... inside sdr-rx" call two paragraphs up: safe to extend once confirmed
  `TOPIC_STT` (`bus.py`) has exactly one consumer in this codebase (`live_audio`'s
  subscriber, `TOPIC_PREFIX = "stt."`) -- `stt_worker`'s real transcription pipeline
  subscribes to `segment_capture`'s `capture.*` topic instead, itself fed from
  `same.<site>.<channel>` (raw discriminator `audio`, read before the squelch/voice-filter
  gate, same as the ring buffer), so gating `TOPIC_STT` cannot touch alert-relevant
  transcription. Reused `LIVE_AUDIO_CHANNELS` rather than an `SDR_RX_*`-named var -- both
  processes run in the one `sdr-rx` container and compose.yaml's `environment:` block is
  shared between them, so one variable is simpler for an operator than two that always need
  to move together. `DevicePipeline.__init__` gained `stt_channels: frozenset[str] | None`;
  `process()` now publishes `TOPIC_SAME` (and writes the ring buffer, samples health)
  unconditionally per channel as before, then skips voice-filter/squelch/resample/encode/
  `TOPIC_STT`-publish entirely for a channel outside the set. `sdr_rx` 126 passed (up from
  124) -- two new cases cover the STT topic being absent for a gated-out channel while SAME
  and the ring buffer still see it, and `None` still running STT for every channel unchanged.

- **2026-08-09 — sdr-rx lost its USB passthrough; alert areas and the services panel were
  unreadable.** Reported from a live PDX station: `rtlsdr_get_device_usb_strings(0..2)
  failed` for all three dongles, then `rtlsdr_get_index_by_serial(49435794) - -3` and "no
  devices started successfully", with the container crash-looping on entrypoint.sh's exit-1
  retry. Bisected to `2e9ce4e`, which moved `sdr-rx`'s `devices: /dev/bus/usb` out of
  `compose.yaml` into a new `compose.sdr.yaml` overlay. The motivation was sound -- Docker
  refuses to *start* a container whose `devices:` host path is absent, which made the whole
  stack unbringable on a machine with no USB subsystem -- but nothing was updated to opt
  back in where hardware exists: `.env.example` still shipped
  `COMPOSE_FILE=compose.yaml:compose.mesh.yaml`, the README bring-up runbook never mentioned
  the overlay, and `make sdr-devices`/`up-offgrid`/`up-hybrid` all shell out to bare
  `docker compose`, inheriting the omission from `.env`.

  Fixed on the principle that offgrid and hybrid are *deployment* modes and both assume the
  SDR is attached -- the `dev-*` targets are the only hardware-free path. `up-offgrid`,
  `up-hybrid`, and `down` now read `COMPOSE_FILE` out of `.env` and append `compose.sdr.yaml`
  if it's absent, exporting the result (a shell value outranks `.env`'s). Deliberately not a
  fixed `-f` list: `COMPOSE_FILE` is also the single switch for `compose.mesh.yaml`, so
  hardcoding would silently drop a user's Meshtastic node. `sdr-devices` *does* pass explicit
  `-f compose.yaml -f compose.sdr.yaml` -- a dongle-enumeration diagnostic wants exactly the
  base plus the USB mapping regardless of whether `.env` exists, and the mesh overlay's
  serial mapping is irrelevant to it. `dev-stack` passes explicit `-f compose.yaml`, ignoring
  `COMPOSE_FILE` entirely, so it stays runnable on Windows/Mac.

  The compose fix alone would leave the same trap for anyone editing `.env` by hand, so
  `prerequisites.py` gained `assert_usb_bus_mapped()` beside the existing DVB-blacklist
  check: Docker's default `/dev` has no `bus/`, so that directory exists only because the
  overlay mapped it. Ordering matters -- it runs *after* `main()`'s `not devices` early
  return, because `make dev-stack` legitimately runs with no bus mapped and must still reach
  its exit 0 (entrypoint.sh stops retrying only on 0; raising ahead of that check would
  crash-loop the container that the 2026-08-08 `restart: unless-stopped` entry already fixed
  once). In the `SDR_RX_LIST_DEVICES` path it runs unconditionally, since that's exactly the
  invocation the operator hit.

  Same session, from the live UI: alert cards printed raw SAME codes
  (`053001 · 053003 · 053007 · …`, thirteen of them) as the area line. Two causes. `data/fips.csv`
  carried 20 rows -- 14 Oregon counties plus the 6 Washington ones bordering the Columbia --
  and the alert was eastern Washington, so `countyName` fell through to its raw-code
  fallback for every entry. Filled the table out to complete state sets, 36 OR + 39 WA (75
  rows); all 13 codes from the report now resolve. Separately, raw codes were being shown
  even when better text existed: NWS ships plain prose in CAP's `areaDesc`, so `areaLabel()`
  now prefers it, falls back to `fips.csv` county names, and only then to raw codes -- and
  truncates past three entries with the full list on the card's `title`, since a dozen-plus
  counties buried the alert's actual content.

  Services panel: dropped `.service-list` from `auto-fill, minmax(170px, 1fr)` (three columns
  on a desktop panel) to a fixed two, one column under 620px. The detail chip moved out of
  the name/age row onto its own line -- at 170px it had been wrapping "segment-capture" onto
  two lines and stacking "polled 34 seconds ago" into a three-line block. Chip text was
  jargon nobody outside the codebase could read, so `chain: remote` → `transcribing: remote`,
  `polled …` → `NWS checked …`, `3 dev` → `3 radios`, each with a `title` sentence saying
  what it measures.

  Verified: `sdr_rx` 132 passed (up from 126) -- 4 new `test_prerequisites.py` cases for the
  bus check plus 2 new `test_main.py` cases for its wiring (fails naming `compose.sdr.yaml`
  when devices are configured; still exits 0 when they aren't), and an autouse fixture stubs
  the check for the pre-existing tests, which run on machines with no USB. `dispatcher` 115
  passed and `api` 111 passed against the expanded `fips.csv`. `web` typechecks and builds.
  `make -n` confirms each target's resolved compose file list against a legacy `.env`. Not
  verified: the real dongles -- no USB subsystem in this sandbox, the same gap the 2026-08-08
  entry records, so the operator's `make sdr-devices` is the actual test of the fix.

- **2026-08-10** — External-reverse-proxy readiness pass (Phase 8 notes above have the full
  writeup): `GET /stream/{mount_path}` for single-port Icecast exposure through `api`,
  `CORS_ALLOWED_ORIGINS` (default `*`, unchanged for existing deployments), Icecast
  source/admin passwords now templated from `.env` instead of hardcoded in `icecast.xml`, and
  `make db-clear-alerts` to drop `alerts` rows from a misconfigured `NWS_POLLER_AREAS`/
  `NWS_POLLER_ZONES` and force a clean resync. `api` 118 passed (up from 115); `docker compose
  config` and `make -n` both confirmed clean. No migration framework added -- `ensure_schema`
  already applies `schema.sql` idempotently on every start, which already covers "automatic
  DB updates" for whatever schema changes come next.

- **2026-08-10 (later same day)** — Two follow-ups from the user. (1) Removed the Meshtastic
  MQTT fallback entirely (Phase 7 notes above have the full writeup) -- they connect only via
  serial/TCP and judged the ack-fallback leg not worth the node-side MQTT config it required.
  `dispatcher` 110 passed (down from 122, MQTT-only tests removed, nothing converted). (2) Cut
  the long-winded rationale comments in `.env.example` and `compose.yaml` down to one line
  each (rarely two) -- per the user, these are what an operator reads first and shouldn't
  bury the value/gotcha under paragraphs of history. Verified `compose.yaml`'s trim was
  comment-only by diffing `docker compose config`'s resolved output before and after (byte
  identical). Added a "Comments and abstractions" note to `CLAUDE.md`/`AGENTS.md` codifying
  this for future work, especially in those two files. Left `docs/design/master-prompt.md`
  untouched for the MQTT removal, per that file's own explicit "don't edit this file to
  reflect implementation decisions" instruction -- the roadmap/tracking updates are where
  that kind of change belongs, which is what this entry and the roadmap.md edit are. Full
  suite green: 132/29/37/48/52/30/43/110/118 passed across all eight services plus `web`
  build.

- **2026-08-10 (documentation catch-up):** Several of the same-day changes above (dashboard
  tabs, the weather map, NWR station data moving to `data/nwr_stations/`, radius/zone
  filtering, alert dedup and stable `API_ONLY` ids, persisted `SeenAlertTracker` state, the
  mobile/PWA fixes, the logo) had landed without their READMEs catching up, at the user's
  request to bring the docs into line. Root `README.md`: added a "Web UI" section (the
  Dashboard/Activity tabs, the map, the PWA install path -- none of it was mentioned at all
  before), fixed the repository-layout tree to show `data/nwr_stations/` instead of a single
  flat file, and replaced the "Build order" section's phase-by-phase narrative -- which had
  drifted into duplicating this document at increasing length every session -- with a short
  "Status" section that states the headline facts (all eight milestones unit-tested; Phases 1
  and 3 live-hardware-verified; no real SAME header decoded yet) and points here for anything
  more specific, trimming ~35 lines of content this file already carries better. Also trimmed
  two self-referential asides in "Hardware bring-up" about this repo's own authoring sandbox
  having no USB subsystem, which read as noise to an operator following the runbook.
  `web/README.md`'s "Layout" section still described the pre-tab single-page two-column
  design; rewrote it for the Dashboard/Activity split and added a "What's on the page" entry
  for `views/map.ts`. `services/api/README.md` and `data/README.md` still named the old flat
  `nwr_stations_or.yaml` in two places each (`data/README.md` was already correct); fixed the
  stragglers in `api/README.md`'s configuration table. `services/nws_poller/README.md`'s
  configuration table was missing `NWS_POLLER_STRICT_ZONE_FILTER` and
  `NWS_POLLER_MAX_RADIUS_MILES` entirely (present in code and `.env.example` since this
  morning's Phase 5 entry, absent from the README); added both, plus a note that
  `NWS_POLLER_REDIS_URL` now also backs the persisted seen-tracker, not just the CAP sink.
  `services/fusion/README.md`'s Status section didn't mention the in-place dedup or
  deterministic `API_ONLY` ids; added a paragraph. Separately, found and fixed one real (if
  cosmetic) leftover bug while grepping for stale MQTT references after the 2026-08-10 MQTT
  removal earlier this file: `web/src/views/status.ts`'s hybrid-mode chip tooltip still read
  "NWS API polling, remote STT, and MQTT fallback are active" -- that removal's own commit
  never touched this string, since nothing in its diff was named `meshtastic`/`mqtt` and nobody
  grepped the UI copy itself. Now reads "...and LLM enrichment are active," matching what
  hybrid mode actually turns on today (design doc §8: NWS polling, remote STT, stage-2 LLM
  enrichment -- no MQTT leg exists anymore). No code behavior changed by this pass beyond that
  one string; everything else was documentation-only.
- **2026-08-11** — Fixed the "new logo isn't showing up after a rebuild" report. The logo
  itself was fine: the redesign (`6bea7e0`) is on `main`, `web/public/`'s five icon files all
  carry the new mark, and a clean `npm run build` copies them into `dist/` byte-identical. The
  bug was on the serving side. `api` mounts the built SPA with a bare Starlette `StaticFiles`,
  which sends `last-modified`/`etag` but no `Cache-Control`, so browsers fall back to
  heuristic freshness on `index.html`, `favicon.svg`, and the PNGs -- all stable filenames
  that nothing ever evicts -- and keep painting the previous logo for days regardless of how
  many times the container is rebuilt. Added `_SpaStaticFiles` in `app.py`: `no-cache`
  (revalidate, cheap via the existing ETag) for stable-named files, `max-age=31536000,
  immutable` for Vite's fingerprinted `assets/` output, which is the split that mount always
  should have had. That fixes future logo changes; for caches already poisoned, bumped a `?v=2`
  on the icon URLs in `index.html` and `manifest.webmanifest` -- bump it again on the next
  logo change. Two new tests in `services/api/tests/test_app.py` pin both header cases; 120
  api tests pass.
- **2026-08-13** — A user's real deployment decoded a live NWR Required Weekly Test
  (`RF ONLY`, confidence 0.60) on the dashboard, closing Phase 2's long-open live-hardware
  gap — marked Phase 2 Done and updated Phase 8's "Depends on" note, which was still saying
  no real SAME header had ever been decoded. The same session asked why that RWT didn't
  reach the Meshtastic node: expected, not a bug — RWT is Tier C and `Stage1Dispatcher` only
  ever sends Tier A (Phase 6's notes, this date). Separately, answered a question with no
  existing behavior to point to: expired alerts had no retention policy at all and stayed in
  Postgres forever. Added a background sweep (`api/__init__.py`'s `_prune_alerts_forever`,
  `ALERTS_PRUNE_GRACE_SECONDS` default 86400/1 day, `ALERTS_PRUNE_INTERVAL_SECONDS` default
  3600) that deletes alerts past that grace window, via a new `db.alert_expiry`/
  `db.prune_expired_alerts` pair — `alert_expiry` is a Python port of `web/src/format.ts`'s
  `expiresAt`, kept unit-testable without a real Postgres rather than pushed into a JSONB SQL
  expression. 8 new tests, 128 api tests pass (up from 120).
