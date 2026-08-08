FROM python:3.11-slim

# multimon-ng is a standalone binary here too (see same_decoder's Dockerfile
# comment) -- segment_capture runs its own instance, independently of
# same_decoder's, to detect ZCZC/NNNN without depending on that service.
RUN apt-get update && apt-get install -y --no-install-recommends \
        multimon-ng \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY README.md ./

RUN uv sync --frozen --no-dev

# Not build-verified against a real container with a shared ring-buffer
# volume: no Docker daemon with USB/tmpfs-sharing to test against in the
# authoring sandbox (see docs/design/tracking.md).
CMD ["uv", "run", "segment-capture"]
