# Build context is the repo root (see compose.yaml's `context: .` for this
# service) -- this image also installs same_decoder, live_audio, and
# segment_capture (formerly their own containers; see entrypoint.sh for
# why they now share this one, keeping the device-owning process's name
# since it's the reason this container exists).
#
# debian:bookworm-slim, not python:3.11-slim -- same reason as before the
# merge: SoapySDR's Python bindings (python3-soapysdr) are a compiled apt
# package built against Debian's own python3, and mixing a Debian-compiled
# extension module with a separately-built CPython interpreter risks
# loading two incompatible libpython3.11 copies into one process. The
# other three projects don't need SoapySDR, but staying on one base image
# for all four is simpler than mixing base images in a single Dockerfile,
# and multimon-ng/ffmpeg are just as happy as Debian packages here as they
# were on python:3.11-slim.
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-soapysdr \
        soapysdr-module-rtlsdr \
        soapysdr-tools \
        multimon-ng \
        ffmpeg \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# sdr-rx: --system-site-packages so its venv can see apt's SoapySDR
# bindings, which live in Debian python3's site-packages, not in any venv
# uv would otherwise create in isolation (see the FROM comment above).
WORKDIR /app/sdr_rx
COPY services/sdr_rx/pyproject.toml services/sdr_rx/uv.lock ./
COPY services/sdr_rx/src ./src
COPY services/sdr_rx/README.md ./
RUN uv venv --system-site-packages --python python3 && uv sync --frozen --no-dev

# same_decoder, live_audio, segment_capture: no SoapySDR dependency, plain
# venvs against the same system python3 (avoids uv separately downloading
# a second interpreter per project).
WORKDIR /app/same_decoder
COPY services/same_decoder/pyproject.toml services/same_decoder/uv.lock ./
COPY services/same_decoder/src ./src
COPY services/same_decoder/README.md ./
RUN uv venv --python python3 && uv sync --frozen --no-dev

WORKDIR /app/live_audio
COPY services/live_audio/pyproject.toml services/live_audio/uv.lock ./
COPY services/live_audio/src ./src
COPY services/live_audio/README.md ./
RUN uv venv --python python3 && uv sync --frozen --no-dev

WORKDIR /app/segment_capture
COPY services/segment_capture/pyproject.toml services/segment_capture/uv.lock ./
COPY services/segment_capture/src ./src
COPY services/segment_capture/README.md ./
RUN uv venv --python python3 && uv sync --frozen --no-dev

WORKDIR /app
COPY services/sdr_rx/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

CMD ["./entrypoint.sh"]
