# Build context is the repo root (see compose.yaml's `context: .` for this
# service), not services/api/ -- this stage needs to reach into web/ to
# build the SPA that used to be its own nginx container. See
# web/README.md and this file's `web` stage for why.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json ./
RUN npm install
COPY web/ .
RUN npm run build

FROM python:3.11-slim

# Pure Python (FastAPI/uvicorn/asyncpg/redis) -- no apt packages needed,
# unlike sdr-rx's SoapySDR or same-decoder's multimon-ng.
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY services/api/pyproject.toml services/api/uv.lock ./
COPY services/api/src ./src
COPY services/api/README.md ./

RUN uv sync --frozen --no-dev

# API_STATIC_DIR's default (config.py) -- create_app mounts it at "/" if
# present, formerly web/nginx.conf's job.
COPY --from=web /web/dist ./static

CMD ["uv", "run", "api"]
