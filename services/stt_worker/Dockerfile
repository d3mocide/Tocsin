FROM python:3.11-slim AS whisper-build

# No apt package exists for whisper.cpp on a Debian stable base -- it only
# landed in Debian *unstable* in January 2026 and is already marked for
# testing-autoremoval (see docs/design/tracking.md) -- so it's built from
# source here, same reasoning as deploy/icecast building its own image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git cmake build-essential \
    && rm -rf /var/lib/apt/lists/*

# Pinned to the latest tagged stable release (v1.9.2 as of this writing)
# for a reproducible build rather than tracking master.
RUN git clone --branch v1.9.2 --depth 1 https://github.com/ggml-org/whisper.cpp /whisper.cpp \
    && cmake -B /whisper.cpp/build -S /whisper.cpp \
    && cmake --build /whisper.cpp/build -j --config Release

FROM python:3.11-slim

COPY --from=whisper-build /whisper.cpp/build/bin/whisper-cli /usr/local/bin/whisper-cli

# whisper.cpp links against libgomp (OpenMP) for CPU threading at runtime,
# not just build time -- python:3.11-slim doesn't ship it by default. Both
# stages share the same base image, so (unlike sdr-rx's SoapySDR situation)
# there's no interpreter/glibc ABI mismatch risk for the copied binary.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY README.md ./

RUN uv sync --frozen --no-dev

# Not build-verified: this sandbox's network proxy has previously blocked
# similar git-clone-then-compile steps (see docs/design/tracking.md), and
# whisper.cpp's own build wasn't attempted here as a result. The Python
# side (subscriber, trim, whisper-cli subprocess wrapper, hallucination
# guard, service wiring) is unit tested against a stand-in instead of the
# real binary -- see README.md's "Status" section.
CMD ["uv", "run", "stt-worker"]
