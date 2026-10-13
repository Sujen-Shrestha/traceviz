# syntax=docker/dockerfile:1

# --- UI: build the React app from its lockfile ---
FROM node:22.22.1-trixie-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN npx -y pnpm@10.34.6 install --frozen-lockfile
COPY frontend/ ./
RUN npx -y pnpm@10.34.6 build

# --- App: Python package + mtr + baked-in geolocation data ---
FROM python:3.13.13-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /usr/local/bin/uv
RUN apt-get update \
 && apt-get install -y --no-install-recommends mtr-tiny ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    TRACEVIZ_DATA_DIR=/data \
    TRACEVIZ_GEO_DIR=/opt/traceviz/geo \
    TRACEVIZ_STATIC_DIR=/opt/traceviz/static
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# IP geolocation by DB-IP (https://db-ip.com), licensed CC BY 4.0
RUN traceviz fetch-geo
COPY --from=ui /ui/dist /opt/traceviz/static

VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)" || exit 1
ENTRYPOINT ["traceviz"]
CMD ["serve"]
