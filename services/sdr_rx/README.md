# sdr-rx

Owns the RTL-SDR dongle(s). Custom SoapySDR + numpy polyphase channelizer --
see `../../docs/` and the repo root README for the full design.

## Status

The 48-bin odd-stacked polyphase channelizer (`src/sdr_rx/channelizer.py`),
DC blocker, discriminator, resampling, channel/bin mapping, ZMQ PUB
publisher (`bus.py`), tmpfs ring buffer (`ring_buffer.py`), health signal
(`health.py`), host-prerequisite check (`prerequisites.py`), and the
pipeline that wires them together (`pipeline.py`) are implemented and unit
tested. `SoapySDRDevice` (`capture.py`) is written against the SoapySDR
Python API but is untestable without target hardware and the SoapySDR
bindings installed -- everything upstream of it (`DevicePipeline`) is
exercised in tests via a fake sample source instead, so the whole path
except actual device I/O is proven without RF.

The Dockerfile now installs the SoapySDR system packages (`python3-soapysdr`,
`soapysdr-module-rtlsdr`) via apt on a `debian:bookworm-slim` base -- see the
Dockerfile's own comment for why it isn't `python:3.11-slim`. **Not
build-verified** (no Docker daemon in the authoring sandbox); if `uv run
sdr-rx` can't `import SoapySDR` inside the container, that's the first thing
to check (see the Dockerfile's fallback note).

**Not yet verified on target hardware:** all seven WX channels locking on a
real dongle, CPU headroom on a Pi 5 (`make bench-channelizer` has only run
on the dev sandbox), and the full bring-up sequence below end to end.

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
| `SDR_RX_LIST_DEVICES` | *(unset)* | If set (any value), enumerate visible rtlsdr devices and exit instead of starting capture -- see `make sdr-devices`. |
| `SDR_RX_ZMQ_BIND` | `tcp://0.0.0.0:5555` | ZMQ PUB bind address for the `same.<site>.<channel>` / `stt.<site>.<channel>` topics (see `bus.py`). |
| `SDR_RX_RING_BUFFER_DIR` | `/tmp/sdr_rx_ring` | Base directory for the per-site, per-channel tmpfs ring buffers -- mount this on tmpfs in production. |

## Development

```sh
uv sync
uv run pytest
```
