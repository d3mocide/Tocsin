FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY README.md ./

RUN uv sync --frozen --no-dev

# Milestone 1 only: the channelizer library has no SoapySDR capture loop or
# ZMQ publisher wired up yet (see docs/design-spec.md §10, and this
# service's README). This entrypoint prints status and exits rather than
# pretending to run a capture pipeline that doesn't exist.
CMD ["uv", "run", "sdr-rx"]
