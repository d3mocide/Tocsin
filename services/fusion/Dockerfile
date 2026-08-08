FROM python:3.11-slim

# No apt packages needed -- pure Python (pyyaml + redis), no subprocess
# dependency like same-decoder's multimon-ng or sdr-rx's SoapySDR.
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY README.md ./

RUN uv sync --frozen --no-dev

CMD ["uv", "run", "fusion"]
