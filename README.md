# traceviz

**See where your packets go.** traceviz is a visual traceroute and MTR-style route monitor. It shows each hop
on a world map as it is discovered and tells you where latency and packet loss start, from both your
terminal and your browser.

- **Live world map**: hops appear as they are discovered, with arcs that follow the real route.
- **Per-hop stats**: loss, sent, last/avg/best/worst RTT and jitter, plus location and ASN for every hop.
- **Route summary**: countries and networks crossed, the biggest latency jumps, and plain-language notes.
- **Monitor mode**: probes continuously, MTR-style, with live latency charts.
- **History**: every trace is saved to SQLite and shared between the CLI and the web UI.
- **Runs offline**: geolocation comes from bundled DB-IP Lite databases, so no IP lookup API is called.
- **One Docker image**: the web UI, the CLI, `mtr` and the geo data ship together and run as an unprivileged user.

Traces can use ICMP, UDP or TCP (port 443).

---

## Contents

- [Quick start (Docker)](#quick-start-docker)
- [Quick start (local)](#quick-start-local)
- [CLI reference](#cli-reference)
- [Web UI](#web-ui)
- [Configuration](#configuration)
- [How it works](#how-it-works)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Attribution](#attribution)

---

## Quick start (Docker)

The image contains everything: the web UI, the CLI, `mtr` and the geolocation databases.

**Linux** uses host networking, so traces start from your machine and not from a container NAT hop:

```bash
git clone https://github.com/Sujen-Shrestha/traceviz.git
cd traceviz
docker compose up -d --build
```

Open **http://127.0.0.1:8080**.

**Mac / Windows (Docker Desktop):**

```bash
docker compose -f compose.yaml -f compose.desktop.yaml up -d --build
```

On Docker Desktop, the first one or two hops belong to Docker's VM and show as `local`.

**Using the CLI from the container.** `docker compose build` creates the `traceviz` image:

```bash
docker run --rm -it --init --network host -v ./data:/data traceviz trace google.com
docker run --rm -it --init --network host -v ./data:/data traceviz monitor 1.1.1.1
docker run --rm      --init --network host -v ./data:/data traceviz history
```

History is shared with the web UI through `./data`, and `docker stop` saves sessions that are still running.

**Refreshing the geolocation data.** The DB-IP databases are downloaded at build time and cached in
their own layer. To pull a newer month:

```bash
docker compose build --build-arg GEO_MONTH=$(date +%Y-%m)
```

<details>
<summary><b>Permissions, rootless Docker and Podman</b></summary>

- The container runs as an unprivileged user (uid 1000), and files in `./data` belong to that uid.
- With rootless Docker or Podman, container uid 1000 maps to one of your sub-UIDs. Remove those files with
  `podman unshare rm …` or `docker run --rm -v ./data:/data --entrypoint rm traceviz …`.
- Probing uses a setuid `mtr-packet`, so the container needs the `NET_RAW` capability. Docker grants it by
  default. On Podman or any other runtime that drops it, add `--cap-add NET_RAW`.
- Don't run the container with `--security-opt no-new-privileges`, because that stops `mtr-packet` from working.
- `traceviz doctor` tells you if probing is blocked.

</details>

---

## Quick start (local)

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/) and `mtr` (on Debian/Ubuntu, `sudo apt install mtr-tiny`).

```bash
uv sync
uv run traceviz doctor           # checks mtr permissions, geo DB and database path
uv run traceviz fetch-geo        # downloads the free DB-IP Lite databases (~130 MB)
uv run traceviz trace google.com
uv run traceviz monitor 1.1.1.1  # Ctrl-C to stop
uv run traceviz history
```

---

## CLI reference

| Command | What it does |
|---|---|
| `traceviz trace TARGET` | Traces the route to `TARGET` once and prints a live-updating hop table. |
| `traceviz monitor TARGET` | Probes the route continuously, MTR-style. Ctrl-C stops it and saves the results. |
| `traceviz history` | Lists past traces. |
| `traceviz serve` | Starts the web UI and API. |
| `traceviz doctor` | Checks that probing, geolocation and storage are ready. |
| `traceviz fetch-geo` | Downloads the DB-IP Lite city and ASN databases. |

Common options:

| Option | Applies to | Default |
|---|---|---|
| `--protocol`, `-p` `icmp\|udp\|tcp` | trace, monitor | `icmp` (tcp uses port 443) |
| `--max-hops N` | trace, monitor | `30` (max 64) |
| `--cycles N` | trace | `10` probes per hop |
| `--json` | trace, history | off: prints machine-readable output |
| `--target HOST`, `--limit N` | history | all targets, `20` |
| `--host`, `--port`, `--trusted-host` | serve | `127.0.0.1`, `8080` |

Example for scripting:

```bash
uv run traceviz trace 1.1.1.1 --protocol tcp --json > trace.json
```

---

## Web UI

Build the frontend once. You need Node 20+. pnpm runs through `npx`, so nothing is installed globally.

```bash
npx -y pnpm@10.34.6 --dir frontend install
npx -y pnpm@10.34.6 --dir frontend build
uv run traceviz serve            # http://127.0.0.1:8080
```

Enter a host, choose **Trace** or **Monitor**, and watch the hops appear on the map. Closing the tab stops
a running probe.

`serve` listens on `127.0.0.1` only. `--host 0.0.0.0` exposes it to your network, and traceviz prints a
warning when you do that. Requests are checked against the allowed host names and origins, so a malicious
website can't drive the API through your browser. Add any extra names with `--trusted-host`.

**Hot reload:** run `uv run traceviz serve`, and in a second terminal run
`npx -y pnpm@10.34.6 --dir frontend dev`. Vite proxies `/api` and `/ws` to port 8080.

### API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Probe readiness, geo availability, attribution |
| `POST` | `/api/sessions` | Starts a trace or monitor session (`target`, `kind`, `protocol`, `max_hops`, `cycles`) |
| `GET` | `/api/sessions/{id}` | Current snapshot of a session |
| `POST` | `/api/sessions/{id}/stop` | Stops a session |
| `WS` | `/ws/sessions/{id}` | Streams session state while it runs |

---

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `TRACEVIZ_DATA_DIR` | `~/.local/share/traceviz` (`/data` in Docker) | SQLite history database |
| `TRACEVIZ_GEO_DIR` | `$TRACEVIZ_DATA_DIR/geo` | DB-IP `.mmdb` files |
| `TRACEVIZ_STATIC_DIR` | `frontend/dist` | Built web UI served by `serve` |

---

## How it works

```
                ┌──────────────┐     ┌──────────────┐
  Typer CLI ───►│              │     │  ProbeEngine │── mtr --raw ──► network
                │   Session    │────►│  (MtrEngine) │
  FastAPI   ───►│   manager    │     └──────────────┘
  REST + WS     │              │────► GeoLookup (DB-IP Lite .mmdb, offline)
     ▲          │              │────► Store (SQLite via SQLModel)
     │          └──────┬───────┘
     └── React UI ◄────┘  live TraceState updates
         (d3-geo map, uPlot charts)
```

- **`core/probe`** runs `mtr --raw` and parses its output into hop events.
- **`core/geo`** maps IPs to city, country and ASN using local DB-IP Lite databases, and marks private
  addresses as `local`.
- **`core/sessions`** is the only orchestrator. It combines probe and geo data into a `TraceState`,
  publishes updates to subscribers and saves results.
- **`core/store`** is the SQLite persistence layer that the CLI and web UI share.
- **`web/`** is a FastAPI app with REST endpoints and a WebSocket stream, and it serves the built React app.
- **`cli/`** holds the Typer commands and renders them with Rich.
- **`frontend/`** is React + TypeScript built with Vite. It uses a d3-geo world map from Natural Earth
  outlines (no tile server) and uPlot latency charts.

---

## Development

```bash
uv run pytest                                  # Python unit tests
uv run pytest -m slow                          # real mtr against 1.1.1.1 (needs network)
npx -y pnpm@10.34.6 --dir frontend test        # frontend tests (Vitest)
npx -y pnpm@10.34.6 --dir frontend typecheck
```

Project layout:

```
src/traceviz/
  cli/        Typer commands + Rich rendering
  core/       probe · geo · sessions · store
  web/        FastAPI app + serialization
frontend/     React + TypeScript UI
tests/        unit, web, and integration (Docker, real mtr) tests
docker/       container entrypoint
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `mtr: failed` in `traceviz doctor` | Install `mtr-tiny`. In Docker, make sure `NET_RAW` is granted and `no-new-privileges` is not set. |
| Every hop shows `unknown location` | Run `traceviz fetch-geo` (local) or rebuild the image. |
| The first hops show `local` on Mac/Windows | Expected, because they are Docker Desktop's VM. |
| Can't delete files in `./data` | They belong to container uid 1000. See [Permissions](#quick-start-docker). |
| `serve` returns 404 at `/` when run locally | Build the frontend first (see [Web UI](#web-ui)). |

---

## Attribution

- IP geolocation by [DB-IP](https://db-ip.com), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- Map data from [Natural Earth](https://www.naturalearthdata.com/) (public domain) via [world-atlas](https://github.com/topojson/world-atlas).
