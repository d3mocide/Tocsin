FROM python:3.11-slim

# Pure Python (FastAPI/uvicorn/asyncpg/redis) -- no apt packages needed,
# unlike sdr-rx's SoapySDR or same-decoder's multimon-ng.
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY README.md ./

RUN uv sync --frozen --no-dev

CMD ["uv", "run", "api"]
