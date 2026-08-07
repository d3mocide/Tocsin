FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY README.md ./

RUN uv sync --frozen --no-dev

# SoapySDR (rtlsdr module) isn't pip-installable -- it's a system package
# (soapysdr-module-rtlsdr + its Python bindings) that this image doesn't
# install yet, since it can't be verified without target hardware in the
# authoring sandbox (see this service's README). Without it, or without
# SDR_RX_DEVICES set, the entrypoint reports why and exits cleanly rather
# than pretending to run a capture pipeline that isn't there.
CMD ["uv", "run", "sdr-rx"]
