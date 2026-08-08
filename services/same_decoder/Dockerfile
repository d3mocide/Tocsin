FROM python:3.11-slim

# multimon-ng is a standalone binary (not a Python extension), so unlike
# sdr-rx's SoapySDR bindings there's no interpreter-ABI reason to avoid this
# image's separately-built Python -- it only needs to be on PATH.
RUN apt-get update && apt-get install -y --no-install-recommends \
        multimon-ng \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY README.md ./

RUN uv sync --frozen --no-dev

# Not build-verified: no Docker daemon in the authoring sandbox (see
# docs/design/tracking.md).
CMD ["uv", "run", "same-decoder"]
