FROM python:3.11-slim

# ffmpeg is a standalone binary, not a Python extension -- no interpreter-ABI
# concern here (unlike sdr-rx's SoapySDR bindings), it just needs to be on
# PATH.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY README.md ./

RUN uv sync --frozen --no-dev

# Not build-verified: no Docker daemon in the authoring sandbox (see
# docs/design/tracking.md).
CMD ["uv", "run", "live-audio"]
