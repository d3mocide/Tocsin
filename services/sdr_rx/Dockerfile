# debian:bookworm-slim, not python:3.11-slim -- deliberately. SoapySDR's
# Python bindings (python3-soapysdr) aren't pip-installable; they're a
# compiled apt package built against Debian's own python3. The official
# python:3.11-slim image ships a *separately built* CPython 3.11, and mixing
# a Debian-compiled extension module with a differently-built interpreter
# risks loading two incompatible libpython3.11 copies into one process.
# Staying inside Debian's own Python end to end keeps that ABI consistent.
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-soapysdr \
        soapysdr-module-rtlsdr \
        soapysdr-tools \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY README.md ./

# --system-site-packages so the project venv can see apt's SoapySDR
# bindings, which live in Debian python3's site-packages, not in any venv
# uv would otherwise create in isolation.
RUN uv venv --system-site-packages --python python3 && uv sync --frozen --no-dev

# Not build-verified: no Docker daemon in the authoring sandbox (see
# tracking.md). If `import SoapySDR` fails inside the venv despite the apt
# packages above, the likely culprit is --system-site-packages not being
# honored by this uv version -- fall back to `python3 -m venv
# --system-site-packages .venv && .venv/bin/pip install -e .` and drop uv
# from the run path as a diagnostic step.
CMD ["uv", "run", "sdr-rx"]
