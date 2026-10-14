# syntax=docker/dockerfile:1
# Base images are pinned by digest (tags checked on 2026-10-13/14, all built >2 weeks earlier).

# --- UI: build the React app from its lockfile ---
FROM node:22.22.1-trixie-slim@sha256:285a78d9fdb7cd2e4a03639cc7bbf609755ce8c0aa4e3b00086211e3e86a7038 AS ui
WORKDIR /ui
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN npx -y pnpm@10.34.6 install --frozen-lockfile
COPY frontend/ ./
RUN npx -y pnpm@10.34.6 build

FROM ghcr.io/astral-sh/uv:0.11.8@sha256:3b7b60a81d3c57ef471703e5c83fd4aaa33abcd403596fb22ab07db85ae91347 AS uv

# --- Python base: system packages, unprivileged user, locked dependencies ---
FROM python:3.13.13-slim-trixie@sha256:aa938a849bcb82dce8f49480f056ab82bf5c1c3ebc294f0430f37b6820e7f286 AS base
COPY --from=uv /uv /usr/local/bin/uv
# mtr-tiny is not version-pinned: Debian drops superseded versions from its mirrors,
# which would eventually break every build.
RUN apt-get update \
 && apt-get install -y --no-install-recommends mtr-tiny ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 1000 --user-group --no-create-home --shell /usr/sbin/nologin traceviz
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --- Geolocation data: its own minimal stage (Python + httpx only), so neither code nor
# dependency changes re-download ~130 MB. Refresh with: docker compose build --build-arg GEO_MONTH=YYYY-MM
FROM python:3.13.13-slim-trixie@sha256:aa938a849bcb82dce8f49480f056ab82bf5c1c3ebc294f0430f37b6820e7f286 AS geo
COPY --from=uv /uv /usr/local/bin/uv
RUN uv pip install --system --no-cache httpx==0.28.1
WORKDIR /app
ARG GEO_MONTH=""
COPY src/traceviz/__init__.py src/traceviz/__init__.py
COPY src/traceviz/core/__init__.py src/traceviz/core/__init__.py
COPY src/traceviz/core/geo src/traceviz/core/geo
# IP geolocation by DB-IP (https://db-ip.com), licensed CC BY 4.0
RUN PYTHONPATH=src GEO_MONTH="$GEO_MONTH" python - <<'PY'
import os
from datetime import date
from pathlib import Path

import httpx

from traceviz.core.geo.download import download_latest

month = os.environ.get("GEO_MONTH")
today = date.fromisoformat(f"{month}-15") if month else date.today()
with httpx.Client(timeout=300) as client:
    print("DB-IP Lite", download_latest(Path("/opt/traceviz/geo"), client, today))
PY

# --- Runtime ---
FROM base
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable
COPY --from=geo /opt/traceviz/geo /opt/traceviz/geo
COPY --from=ui /ui/dist /opt/traceviz/static
COPY docker/entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV TRACEVIZ_DATA_DIR=/data \
    TRACEVIZ_GEO_DIR=/opt/traceviz/geo \
    TRACEVIZ_STATIC_DIR=/opt/traceviz/static
VOLUME /data
EXPOSE 8080
# No HEALTHCHECK here: CLI runs share this image. compose.yaml defines it for the server.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["serve"]
