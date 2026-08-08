FROM python:3.11-slim

# meshtastic (PyPI) is pure Python + pyserial/protobuf/pypubsub -- no apt
# system packages needed, unlike sdr-rx's SoapySDR or same-decoder's
# multimon-ng. The serial device itself is passed through at the compose
# level (a host device node, not something apt installs).
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY README.md ./

RUN uv sync --frozen --no-dev

CMD ["uv", "run", "dispatcher"]
