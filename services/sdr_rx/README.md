# sdr-rx

Owns the RTL-SDR dongle(s). Custom SoapySDR + numpy polyphase channelizer --
see `../../docs/` and the repo root README for the full design.

This container also runs `same_decoder`, `live_audio`, and
`segment_capture` (formerly three separate containers) as independent
processes alongside this one -- see "Container" below.

## Status

The 48-bin odd-stacked polyphase channelizer (`src/sdr_rx/channelizer.py`),
DC blocker, discriminator, resampling, channel/bin mapping, ZMQ PUB
publisher (`bus.py`), tmpfs ring buffer (`ring_buffer.py`), health signal
(`health.py`), the 41-spectrum-bin tracker (`spectrum.py`, Phase 8 --
computed for free from the channelizer's already-full 48-bin output, see
its own docstring), squelch + voice-band filtering for the live-audio feed
(`audio_conditioning.py` -- see its docstring for why this is applied to
the `stt` ZMQ topic only, never to SAME decode or the ring buffer
`segment_capture` reads alert audio from), Redis publishing for both
(`redis_sink.py`, `tocsin:health` stream + a per-site
`tocsin:spectrum:<site>` snapshot key for `api`), host-prerequisite check
(`prerequisites.py`), and the pipeline that wires them together
(`pipeline.py`) are implemented and unit tested.
`SoapySDRDevice` (`capture.py`) is written against the SoapySDR Python API
but is untestable without target hardware and the SoapySDR bindings
installed -- everything upstream of it (`DevicePipeline`) is exercised in
tests via a fake sample source instead, so the whole path except actual
device I/O is proven without RF.

**A real bug fixed in Phase 8, not introduced by it:** `HealthTracker` was
shared across every site's `DevicePipeline` in a multi-dongle setup but
keyed samples on `channel` alone, not `(site, channel)` -- two sites' `WX5`
would silently collide, the same bug class already fixed once for this
service's own ZMQ topics (`docs/design/tracking.md`, 2026-08-07). Found
while wiring health data into Phase 8's UI; fixed with a regression test
(`test_same_channel_name_at_different_sites_is_tracked_independently`).

The Dockerfile installs the SoapySDR system packages (`python3-soapysdr`,
`soapysdr-module-rtlsdr`) via apt on a `debian:bookworm-slim` base -- see the
Dockerfile's own comment for why it isn't `python:3.11-slim` -- plus
`multimon-ng` and `ffmpeg` for the three services that now share this
image. If `uv run sdr-rx` can't `import SoapySDR` inside the container,
that's the first thing to check (see the Dockerfile's fallback note).

**Not yet verified on target hardware:** all seven WX channels locking on a
real dongle, CPU headroom on a Pi 5 (`make bench-channelizer` has only run
on the dev sandbox), and the full bring-up sequence below end to end.

**Performance (2026-08-09):** a live deployment report of near-100% CPU on
the `sdr-rx` process led to profiling `DevicePipeline.process()` end to end.
Three real, unrelated-to-each-other inefficiencies came out of it, all fixed
with no behavior change (see `docs/design/tracking.md`'s entry this date for
the full writeup and profiled numbers): `resample.py`'s two `resample_poly`
calls were redesigning their anti-aliasing FIR filter -- one of them ~20,000
taps -- from scratch on every chunk instead of once (over a third of total
CPU time); `ring_buffer.py`'s `write()` called `mmap.flush()` every chunk,
which is pointless on the tmpfs this buffer is documented to live on
(cross-process visibility doesn't need msync for a `MAP_SHARED` mapping of
the same file); and `channelizer.py`'s `_demodulate()` recomputed `exp()` for
every sample of every chunk even though the demodulation ramp only ever
takes 96 distinct values. Combined: ~2.4x throughput improvement on the
sandbox benchmark (1.41x -> 3.44x real-time margin per dongle, single-core).
Still not verified against the actual Pi CPU headroom this was reported
against -- the sandbox's per-core speed is unknown relative to target
hardware, so the *ratio* of improvement is the trustworthy number here, not
the absolute real-time factor.

## Hardware bring-up

See the repo root README's hardware bring-up runbook for the full
multi-service sequence. The `sdr-rx`-specific prerequisites it walks through:

1. **Blacklist the DVB driver on the host** (not the container) -- the
   kernel's `dvb_usb_rtl28xxu` claims the dongle before SoapySDR can open it
   otherwise:
   ```sh
   echo "blacklist dvb_usb_rtl28xxu" | sudo tee /etc/modprobe.d/blacklist-rtlsdr.conf
   sudo rmmod dvb_usb_rtl28xxu   # or reboot
   ```
   `sdr-rx` asserts this at startup (`prerequisites.py`) and refuses to start
   with a clear error if the module is loaded.
1b. **Map the USB bus into the container** -- keep `compose.sdr.yaml` in
   `COMPOSE_FILE` (it's in `.env.example` by default). `sdr-rx` checks for
   `/dev/bus/usb` at startup (`prerequisites.py`) once `SDR_RX_DEVICES` is
   set, because without the mapping libusb counts the dongles but can't open
   them and librtlsdr reports `rtlsdr_get_device_usb_strings failed` plus
   `rtlsdr_get_index_by_serial - -3`, which looks like a bad serial instead.
   `make up-offgrid`/`make up-hybrid`/`make sdr-devices` add the overlay for
   you; `make dev-stack` is the deliberate no-hardware path.
2. **Install the udev rule** so the dongle is group-readable without a
   privileged container:
   ```sh
   sudo cp ../../deploy/udev/60-rtlsdr.rules /etc/udev/rules.d/
   sudo udevadm control --reload-rules && sudo udevadm trigger
   sudo usermod -aG plugdev "$USER"   # log out/in or reboot
   ```
3. **Plug in the dongle**, then find its serial: `make sdr-devices` (from the
   repo root) builds the image and runs `SDR_RX_LIST_DEVICES=1` inside it.
4. **Set `SDR_RX_DEVICES`** (see Configuration below) to `site:serial`, e.g.
   `SDR_RX_DEVICES=home:00000001`, and start the stack.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `SDR_RX_DEVICES` | *(none)* | `site:serial,site2:serial2` -- one dongle per transmitter site, addressed by serial number (never by index; see `capture.py`). Empty means no capture; the process reports that and exits. |
| `SDR_RX_LIST_DEVICES` | *(unset)* | If set (any value), enumerate visible rtlsdr devices and exit instead of starting capture -- see `make sdr-devices`. `entrypoint.sh` special-cases this: it `exec`s straight into sdr-rx's own listing codepath and skips starting same_decoder/live_audio/segment_capture entirely, so `make sdr-devices` stays a quick one-shot diagnostic. |
| `SDR_RX_GAIN_DB` | `30` (`capture.DEFAULT_GAIN_DB`) | Manual RTL-SDR gain in dB, applied to every configured device (design doc §3: AGC oscillates on a constant carrier, so this stays manual). 30 dB is a starting point, not a universal value -- antenna, cable loss, and distance to the transmitter all shift what's correct for a given site; see the root README's "Tweak from there" bring-up step. |
| `SDR_RX_SQUELCH_OPEN_DB` | `8.0` (`audio_conditioning.SQUELCH_OPEN_DB`) | Noise-quieting threshold, in dB, for the live-audio feed's squelch only (see `audio_conditioning.py`). Unlike gain, this is *not* a per-site "starting point" -- the no-carrier reference it's measured against is self-calibrating at runtime, so the default should work across dongles and sites without retuning. Lower it if real audio is getting cut off on a weak channel, raise it if static is still getting through between transmissions. |
| `LIVE_AUDIO_CHANNELS` | *(unset -- all channels)* | Same variable `live_audio` reads (`services/live_audio/README.md`), not an `SDR_RX_*` name -- both run in this one container. Comma-separated NWR channel allowlist, e.g. `WX5,WX7`: for a channel outside it, `DevicePipeline.process()` skips the voice-filter/squelch/resample/encode work and never publishes to the `stt.<site>.<channel>` topic at all, since `live_audio` is that topic's only consumer and would otherwise just discard the result. SAME decode, the ring buffer, and health stay on every channel regardless -- only the `live_audio`-only work is gated. |
| `SDR_RX_ZMQ_BIND` | `tcp://0.0.0.0:5555` | ZMQ PUB bind address for the `same.<site>.<channel>` / `stt.<site>.<channel>` topics (see `bus.py`). same_decoder/live_audio/segment_capture connect to this over `localhost` now that they run in this same container -- see their own READMEs. |
| `SDR_RX_RING_BUFFER_DIR` | `/tmp/sdr_rx_ring` | Base directory for the per-site, per-channel tmpfs ring buffers -- mount this on tmpfs in production. |
| `SDR_RX_REDIS_URL` | *(unset -- logs in-process only)* | Redis connection URL. When set, health samples publish to the `tocsin:health` stream and spectrum snapshots to `tocsin:spectrum:<site>` for `api` (Phase 8). |

Tuner frequency (`channels.LO_HZ`, 162.4875 MHz) and sample rate
(`capture.SAMPLE_RATE_HZ`, 1.2 MSPS) are deliberately **not** env-configurable,
unlike gain: they're not per-site tuning knobs, they're the channelizer's
own load-bearing assumptions. `LO_HZ` is a bin *edge*, chosen so all seven
nationally-standardized NWR frequencies (162.400-162.550 MHz, fixed
everywhere in the US, not just locally) land inside one capture window at
predictable bin indices (`channels.py`'s odd-stacked math); `SAMPLE_RATE_HZ`
is tied 1:1 to `NUM_BINS * CHANNEL_SPACING_HZ`. Changing either without
also updating the channelizer's bin math would silently mislabel which
channel is which, or break decode outright -- see CLAUDE.md's
"Signal-processing correctness" section on why the channelizer's
implementation hazards aren't optional. What genuinely varies by site
(which of the seven WX channels you can actually hear) isn't a setting at
all -- sdr-rx always monitors all seven simultaneously.

## Container

`Dockerfile` (build context: repo root, not this directory -- see
`compose.yaml`) builds this project plus `../same_decoder`, `../live_audio`,
and `../segment_capture` into four separate venvs in one `debian:bookworm-slim`
image (only this project needs the apt-installed SoapySDR bindings; the
other three don't need `--system-site-packages`). `entrypoint.sh` launches
all four as independent, self-restarting background processes -- none of
them `exec`s into the foreground, because none is the sole "always
required" one: same_decoder/live_audio/segment_capture are all designed to
stay up and idle even when sdr-rx has no dongle configured (the "Bring the
stack up without a dongle first" bring-up step above). sdr-rx's own loop is
the one exception worth knowing about: an exit 0 ("no devices configured")
stops that specific loop from retrying, same as this service's old
`restart: on-failure` used to mean before it had its own container, while
the other three keep retrying regardless. `set -m` plus a `kill` of each
job's whole process group on `SIGTERM`/`SIGINT` is what makes `docker stop`
actually reach the real `uv run <service>` processes, not just the loop
shells around them.

## Development

```sh
uv sync
uv run pytest
```
