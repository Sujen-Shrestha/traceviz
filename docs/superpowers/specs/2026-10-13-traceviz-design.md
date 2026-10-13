# traceviz — Design Spec

Date: 2026-10-13
Status: Approved design, pending spec review

## 1. Intent

A visual traceroute and connection-diagnostics tool that runs on the user's own machine via Docker.

**Goals (all four are in scope):**
- **Diagnose** — find where latency/packet loss occurs on a route; measure internet speed; keep results over time.
- **Portfolio quality** — clean architecture, polished UI, good tests.
- **Shareable** — anyone with Docker can run it with one command.
- **Fun** — watch packets travel across a world map.

**Success criteria:**
- `docker compose up` → open `http://localhost:8080` → trace a host and see hops appear live in a table and on a world map.
- The same image runs terminal commands (`traceviz trace google.com`) and an interactive TUI (`traceviz tui`).
- MTR-style continuous monitoring shows per-hop loss/latency over time.
- Speed test reports latency, jitter, download, upload.
- History persists across restarts and is shared by web, CLI and TUI.

**Non-goals (v1):** user accounts, multi-user/remote hosting, CI pipeline, custom raw-socket probe engine, browser-only (no-server) operation.

## 2. Architecture

One Python package with a front-end-agnostic core and three front-ends, shipped as one Docker image.

```
traceviz/
  core/
    probe/     ProbeEngine interface; MtrEngine wraps `mtr --raw`
    geo/       GeoLookup over DB-IP Lite city + ASN (.mmdb, offline)
    speed/     SpeedTester against Cloudflare speed endpoints
    sessions/  orchestrates probe + geo (+ store), publishes events
    store/     SQLite via SQLModel
  web/         FastAPI: REST + WebSocket; serves built React frontend
  cli/         Typer commands: trace | monitor | speed | history | serve | tui
  tui/         Textual app: tabs Trace / Monitor / Speed / History
frontend/      React + TypeScript (Vite)
```

### 2.1 Unit contracts

| Unit | Responsibility | Interface (sketch) | Depends on |
|---|---|---|---|
| `ProbeEngine` | Emit raw hop observations | `async def run(target, protocol, max_hops, cycles \| None) -> AsyncIterator[HopEvent]` | nothing (MtrEngine: `mtr` binary) |
| `HopEvent` | Data | `index: int, ip: str \| None, rtt_ms: float \| None, lost: bool, ts` | — |
| `GeoLookup` | IP → location/ASN | `lookup(ip) -> GeoInfo \| Local \| Unknown` where `GeoInfo = {lat, lon, city, country, asn, org, approximate}` | `.mmdb` files |
| `SpeedTester` | Measure speed | `async def run() -> AsyncIterator[SpeedProgress \| SpeedResult]` | httpx, Cloudflare |
| `sessions` | Only orchestrator | `start_trace(...)`, `start_monitor(...)`, `stop(id)`, `subscribe(id) -> AsyncIterator[TraceState]`, `run_speed_test()` | probe, geo, speed, store |
| `store` | Persistence + history queries | repositories for traces, hops, monitor samples, speed results; `route_diff(a, b)` | SQLite |

Front-ends (`web`, `cli`, `tui`) depend only on `sessions` and `store` read queries.

### 2.2 Front-ends

**Web (React + TS):**
- **Trace view** — host input + protocol select; live hop table (hop, IP, hostname, location, ASN/org, loss %, last/avg/best/worst, jitter); animated world map with hop markers and arcs between geolocated hops.
- **Monitor view** — same table updating continuously plus per-hop latency/loss time-series charts.
- **Speed view** — run test, live gauge, final results.
- **History view** — speed-over-time chart; list of past traces; route comparison between two traces to the same target.
- Map: offline Natural Earth country outlines, dark stylized theme (no tile server).

**CLI (Typer + Rich):** `trace`, `monitor`, `speed`, `history` with live-updating Rich tables and a compact map; `--json` for scripting. `serve` starts the web app; `tui` launches the TUI.

**TUI (Textual):** tabs mirroring the web views; keyboard-driven; Braille-character world map (Natural Earth outlines projected to the terminal grid) with hop markers and connecting lines.

### 2.3 Docker packaging

- Multi-stage build: Node stage builds `frontend/`; Python slim stage installs the package, `mtr-tiny`, and downloads DB-IP Lite city + ASN databases at build time.
- Entrypoint `traceviz`; default command `serve`.
- Volume `./data` → SQLite database (shared by all front-ends).
- **Linux:** `docker-compose.yml` uses `network_mode: host` so traces originate from the host without an extra NAT hop.
- **Mac/Windows:** `docker-compose.desktop.yml` override uses port mapping `8080:8080`; early hops belonging to the Docker VM are labelled "local/VM".
- Docker grants `NET_RAW` by default; docs show `--cap-add NET_RAW` for environments that drop it.
- Terminal usage: `docker run --rm -it --network host -v ./data:/data traceviz trace google.com`.

### 2.4 External data & attribution

- DB-IP Lite (CC BY 4.0) — attribution shown in the UI footer and README.
- Natural Earth (public domain) for map outlines.
- Cloudflare public speed endpoints (`speed.cloudflare.com/__down`, `__up`) — no key.

## 3. Data flow

### 3.1 Trace (one-shot)
1. Front-end calls `sessions.start_trace(target, protocol, max_hops)` (default protocol ICMP, max_hops 30, 10 cycles).
2. `MtrEngine` spawns `mtr --raw -c 10 <target>` (argument list, no shell) and parses each line into `HopEvent`.
3. On first sighting of a hop IP, `GeoLookup` enriches it. Private, link-local, CGNAT and leading Docker-VM hops are tagged `local` and not plotted on the map.
4. `sessions` folds events into `TraceState` (per hop: loss %, last/avg/best/worst RTT, jitter) and publishes an update per event. Web receives updates over WebSocket; CLI/TUI consume the async iterator in-process.
5. On completion, trace and hops are persisted with status `completed`.

### 3.2 Monitor (continuous)
Same pipeline with `mtr` running without a cycle limit. `sessions` persists aggregated per-hop samples every 10 seconds (not every event). Stops on explicit stop or, for web, when the last WebSocket subscriber disconnects.

### 3.3 Speed test
1. Latency/jitter: 20 small requests.
2. Download: escalating sizes from `__down?bytes=N`.
3. Upload: escalating sizes to `__up`.
Progress events stream to the front-end; the final result is persisted. Optional scheduled tests inside `serve` (interval configurable, e.g. 30 min; **off by default**) feed history charts.

### 3.4 History & comparison
Read-only queries: speed results over time; past traces filtered by target; `route_diff(trace_a, trace_b)` reports hops/ASNs added, removed, or changed.

## 4. Error handling

**Probing**
- Startup self-check: verifies `mtr` is present and raw sockets are permitted; on failure shows an actionable message (e.g. "needs NET_RAW — run with `--cap-add NET_RAW`").
- Target validated as hostname or IP; unresolvable host is a validation error before probing.
- Non-responding hops shown as "no reply" (not an error); map arcs skip them.
- If all hops beyond hop 1 are silent, the UI suggests switching protocol (ICMP / UDP / TCP:443).
- `mtr` crash → session status `failed`; partial results persisted.
- Max 3 concurrent sessions per server; per-session timeout; stopping a session or losing its last subscriber always kills the child process.

**Geolocation**
- Unknown IP → row shows "unknown location", not plotted.
- Anycast/backbone results flagged `approximate`; UI carries a short note that IP geolocation is approximate.
- Missing `.mmdb` → app runs with the map disabled and a banner.

**Speed test**
- Cloudflare unreachable/rate-limited → clear error; nothing persisted.
- Interrupted run → discarded.
- Scheduled tests back off after 3 consecutive failures and record the errors.

**Storage:** schema migrated on startup; SQLite WAL mode so CLI and server can share the file.

**Security:** server binds `127.0.0.1` by default; LAN exposure requires explicit `--host 0.0.0.0`. `mtr` always invoked with an argument list.

## 5. Testing

TDD throughout.

- **Core (pytest):**
  - `MtrEngine` parser against recorded `mtr --raw` fixtures (normal, silent hops, loss, mid-run crash).
  - `GeoLookup` against a tiny test `.mmdb` (public, private, unknown, VM hops).
  - `sessions` with a fake `ProbeEngine`: aggregation math, monitor 10 s batching, process cleanup on stop.
  - `SpeedTester` with `respx`-mocked HTTP: throughput math, progress events, interruption.
  - `store` on in-memory SQLite: migrations, history queries, `route_diff`.
- **Web API:** FastAPI `TestClient` for REST and WebSocket with the fake engine.
- **CLI:** Typer `CliRunner`; `--json` output validated against a schema.
- **TUI:** Textual pilot smoke tests (tabs render, hop table updates from fake events).
- **Frontend:** Vitest + Testing Library for hop table, route-diff view, WebSocket state reducer. Map verified visually.
- **Integration (`@slow`, opt-in):** build image, run `traceviz trace 1.1.1.1 --json` with `NET_RAW`, assert ≥1 hop and a destination.

## 6. Build order

1. Core: probe, geo, sessions, store
2. CLI
3. Web API + React UI with map
4. TUI
5. Speed test + history (core, then all front-ends)
6. Docker packaging

Each step yields something runnable.
