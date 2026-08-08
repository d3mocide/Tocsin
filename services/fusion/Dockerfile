# Build context is the repo root (see compose.yaml's `context: .` for this
# service), not services/fusion/ -- this image also installs nws_poller,
# which used to be its own container (see entrypoint.sh for why they now
# share one). The two stay independent uv projects/venvs here, each built
# exactly as its own standalone Dockerfile used to build it -- no Python
# import crosses the package boundary, only the entrypoint script that
# launches both as separate OS processes.
FROM python:3.11-slim

# No apt packages needed -- pure Python (pyyaml/requests/redis) for both
# projects, unlike sdr-rx's SoapySDR or same-decoder's multimon-ng.
RUN pip install --no-cache-dir uv

WORKDIR /app/fusion
COPY services/fusion/pyproject.toml services/fusion/uv.lock ./
COPY services/fusion/src ./src
COPY services/fusion/README.md ./
RUN uv sync --frozen --no-dev

WORKDIR /app/nws_poller
COPY services/nws_poller/pyproject.toml services/nws_poller/uv.lock ./
COPY services/nws_poller/src ./src
COPY services/nws_poller/README.md ./
RUN uv sync --frozen --no-dev

WORKDIR /app
COPY services/fusion/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

CMD ["./entrypoint.sh"]
