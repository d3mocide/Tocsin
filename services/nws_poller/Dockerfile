FROM python:3.11-slim

# No apt packages needed -- this service is pure Python (requests + redis),
# unlike sdr-rx's SoapySDR/same-decoder's multimon-ng situations.
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY README.md ./

RUN uv sync --frozen --no-dev

CMD ["uv", "run", "nws-poller"]
