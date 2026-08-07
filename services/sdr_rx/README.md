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

**Not yet verified on target hardware:** all seven WX channels locking on a
real dongle, CPU headroom on a Pi 5 (`make bench-channelizer` has only run
on the dev sandbox), the host `dvb_usb_rtl28xxu` blacklist end to end, and
Docker packaging of the SoapySDR system dependency (not yet added to the
Dockerfile -- see its comment).

## Host prerequisite

`dvb_usb_rtl28xxu` must be blacklisted on the **host**, not the container,
or the kernel DVB driver claims the dongle before SoapySDR can open it:

```sh
echo "blacklist dvb_usb_rtl28xxu" | sudo tee /etc/modprobe.d/blacklist-rtlsdr.conf
sudo rmmod dvb_usb_rtl28xxu   # or reboot
```

`sdr-rx` asserts this at startup (`prerequisites.py`) and refuses to start
with a clear error if the module is loaded.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `SDR_RX_DEVICES` | *(none)* | `site:serial,site2:serial2` -- one dongle per transmitter site, addressed by serial number (never by index; see `capture.py`). Empty means no capture; the process reports that and exits. |
| `SDR_RX_ZMQ_BIND` | `tcp://0.0.0.0:5555` | ZMQ PUB bind address for the `same.*`/`stt.*` topics (see `bus.py`). |
| `SDR_RX_RING_BUFFER_DIR` | `/tmp/sdr_rx_ring` | Base directory for the per-site, per-channel tmpfs ring buffers -- mount this on tmpfs in production. |

## Development

```sh
uv sync
uv run pytest
```
