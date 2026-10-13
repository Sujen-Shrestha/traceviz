# traceviz Plan 3: Docker Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One image that runs the web UI (`docker compose up`) and every CLI command (`docker run … traceviz trace host`), with the UI build and the DB-IP databases baked in, and that shuts down cleanly on `docker stop`.

**Architecture:** Multi-stage Dockerfile: a Node stage builds `frontend/dist`; a Python stage installs the package with uv, adds `mtr-tiny`, downloads DB-IP Lite with the app's own `fetch-geo`, and copies the UI in. `compose.yaml` uses host networking on Linux; `compose.desktop.yaml` switches Mac/Windows to a loopback-published port. The CLI learns to treat SIGTERM/SIGHUP like Ctrl-C so container stops save results.

**Tech Stack:** Docker (BuildKit), Compose v2.24+ (`!reset`), python:3.13.13-slim-trixie, node:22.22.1-trixie-slim, ghcr.io/astral-sh/uv:0.11.8, pnpm 10.34.6.

**Spec:** `docs/superpowers/specs/2026-10-13-traceviz-design.md` (section 2.3 Docker packaging; section 4 security). This was "Plan 5" in the original order; it moved ahead of the TUI and speed test at the user's request. Base images were checked on 2026-10-13: all built more than two weeks earlier.

## Global Constraints

- Inside containers the data dir is `/data` (a volume), geo DBs live in `/opt/traceviz/geo`, the built UI in `/opt/traceviz/static`; all set via `TRACEVIZ_*` env vars, never by code paths.
- Linux compose: `network_mode: host` and `serve --host 127.0.0.1` (the UI is reachable only from this machine).
- Desktop compose: container binds `0.0.0.0`, host publishes `127.0.0.1:8080:8080`, and the server still trusts only `localhost`/`127.0.0.1` Host headers.
- Containers run with an init process (`init: true` / `--init`) so signals reach traceviz and mtr children are reaped.
- `docker stop` (SIGTERM) must leave no session in status `running`.
- No `docker push`, no registry, nothing published.

## Review Focus

1. **`docker stop` during a CLI monitor** → SIGTERM saves the session as `stopped` and kills mtr (not a stuck `running` row). Pinned in Task 1 (local SIGTERM test) and Task 2 (container test).
2. **Desktop override exposes the UI to the LAN** → published on 127.0.0.1 only, Host allowlist still enforced. Pinned in Task 1 (`--trusted-host` test) and the compose file.
3. **Image built without network to DB-IP / month not yet published** → `fetch-geo` already falls back a month; a hard failure fails the build loudly rather than shipping a map-less image. Covered by the build step.
4. **Stale UI in the image** → the UI is built inside the image from the lockfile, never copied from the host's `frontend/dist` (excluded by `.dockerignore`). Pinned in Task 2's server test (`/` serves the built `index.html`).
5. **mtr lacks raw sockets in the container** → default Docker caps include NET_RAW; `/api/health` and `traceviz doctor` report it if a runtime drops it. Pinned in Task 2's server test (`probe_ok` true).

---

### Task 1: Container-ready CLI (signals, mtr override, trusted hosts)

**Files:**
- Modify: `src/traceviz/cli/app.py`
- Test: `tests/cli/test_signals.py` (new), `tests/cli/test_app.py` (append)

**Interfaces:**
- Produces: env `TRACEVIZ_MTR` (shell-split command replacing `mtr`, used by tests); `traceviz serve --trusted-host NAME` (repeatable); SIGTERM/SIGHUP stop `trace`/`monitor` like Ctrl-C (monitor exits 0 with "Monitor stopped; results saved.", trace exits 130 with "Trace stopped; partial results saved.").

- [ ] **Step 1: Write the failing tests**

`tests/cli/test_signals.py`:
```python
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_sigterm_stops_monitor_saves_and_kills_mtr(tmp_path):
    capture = tmp_path / "capture.txt"  # unique path so we can find our fake mtr afterwards
    shutil.copy(FIXTURES / "mtr_raw_cloudflare.txt", capture)
    env = {
        **os.environ,
        "TRACEVIZ_DATA_DIR": str(tmp_path),
        "TRACEVIZ_GEO_DIR": str(tmp_path / "nogeo"),
        "TRACEVIZ_MTR": f"{sys.executable} {FIXTURES / 'fake_mtr.py'} hang {capture}",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "traceviz", "monitor", "1.1.1.1"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    time.sleep(2)
    proc.send_signal(signal.SIGTERM)
    _, stderr = proc.communicate(timeout=15)
    assert proc.returncode == 0, stderr
    assert "Monitor stopped; results saved." in stderr
    history = subprocess.run([sys.executable, "-m", "traceviz", "history", "--json"],
                             env=env, capture_output=True, text=True, check=True)
    assert [r["status"] for r in json.loads(history.stdout)] == ["stopped"]
    assert subprocess.run(["pgrep", "-f", str(capture)]).returncode == 1  # fake mtr is gone
```

Append to `tests/cli/test_app.py`:
```python
def test_serve_trusted_hosts_restrict_exposed_server(env, monkeypatch, tmp_path):
    use_engine(monkeypatch, FakeEngine([]))
    capture_server(monkeypatch)
    seen = {}
    real_create_app = cli.create_app

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real_create_app(*args, **kwargs)

    monkeypatch.setattr(cli, "create_app", spy)
    result = runner.invoke(
        cli.app, ["serve", "--host", "0.0.0.0", "--trusted-host", "localhost", "--trusted-host", "127.0.0.1"],
        env={**env, "TRACEVIZ_STATIC_DIR": str(tmp_path / "nodist")},
    )
    assert result.exit_code == 0, result.output
    assert seen["allowed_hosts"] == ("localhost", "127.0.0.1")
    assert "anyone on your network" not in result.output
    assert "answering only to localhost, 127.0.0.1" in result.output


def test_make_engine_honours_traceviz_mtr(monkeypatch):
    monkeypatch.setenv("TRACEVIZ_MTR", "/usr/bin/python3 /tmp/fake mtr.py")
    assert cli.make_engine().command == ["/usr/bin/python3", "/tmp/fake", "mtr.py"]
    monkeypatch.delenv("TRACEVIZ_MTR")
    assert cli.make_engine().command == ["mtr"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/cli -q`
Expected: `test_sigterm_stops_monitor_saves_and_kills_mtr` fails (real mtr is used, and SIGTERM kills the process with returncode -15); `test_serve_trusted_hosts…` fails with `No such option: --trusted-host`; `test_make_engine_honours_traceviz_mtr` fails (`['mtr']` != split command).

- [ ] **Step 3: Implement** — in `src/traceviz/cli/app.py`:

Add imports `import os`, `import shlex`, `import signal`.

Replace `make_engine`:
```python
def make_engine() -> ProbeEngine:
    # TRACEVIZ_MTR replaces the mtr command (tests use it to substitute a fake mtr).
    command = os.environ.get("TRACEVIZ_MTR")
    return MtrEngine(command=shlex.split(command)) if command else MtrEngine()
```

Add, above `_run`:
```python
def _stop_on_termination() -> None:
    """Treat SIGTERM (docker stop) and SIGHUP (closed terminal) like Ctrl-C: cancel the run."""
    loop = asyncio.get_running_loop()
    main = asyncio.current_task()
    assert main is not None
    for sig in (signal.SIGTERM, signal.SIGHUP):
        loop.add_signal_handler(sig, main.cancel)
```

At the top of `_run`, before `resolve_target`, call `_stop_on_termination()`.

Replace the bodies of `trace` and `monitor`:
```python
    try:
        code = asyncio.run(_run(target, "trace", protocol.value, max_hops, cycles, json_out))
    except (KeyboardInterrupt, asyncio.CancelledError):
        err().print("Trace stopped; partial results saved.")
        code = 130
    raise typer.Exit(code)
```
```python
    try:
        code = asyncio.run(_run(target, "monitor", protocol.value, max_hops, 10, False))
    except (KeyboardInterrupt, asyncio.CancelledError):
        err().print("Monitor stopped; results saved.")
        code = 0
    raise typer.Exit(code)
```

In `serve`, add the option and replace the host-trust block:
```python
    trusted_host: Annotated[
        list[str] | None,
        typer.Option("--trusted-host", help="Host name the UI may be reached as (repeatable). "
                     "Default: localhost/127.0.0.1 on loopback, any name when --host exposes it."),
    ] = None,
```
```python
    if trusted_host:
        allowed_hosts = tuple(trusted_host)
    else:
        allowed_hosts = LOCAL_HOSTS if host in _LOOPBACK else ("*",)
    if host not in _LOOPBACK:
        if allowed_hosts == ("*",):
            err().print(f"[yellow]Listening on {host}: anyone on your network can start traces from this machine.[/yellow]")
        else:
            out().print(f"Listening on {host}, answering only to {', '.join(allowed_hosts)}")
```
(delete the previous `if host not in _LOOPBACK:` warning and the previous `allowed_hosts = …` lines.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add src/traceviz/cli/app.py tests/cli/test_signals.py tests/cli/test_app.py
git commit -m "feat: stop cleanly on SIGTERM/SIGHUP; --trusted-host; TRACEVIZ_MTR override"
```

---

### Task 2: Dockerfile, compose files, container tests, docs

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `compose.yaml`, `compose.desktop.yaml`, `tests/integration/test_docker.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 1's signal handling and `--trusted-host`.
- Produces: image `traceviz` (entrypoint `traceviz`, default `serve`); `docker compose up` (Linux), `docker compose -f compose.yaml -f compose.desktop.yaml up` (Mac/Windows).

- [ ] **Step 1: Write the failing container tests** — `tests/integration/test_docker.py`

```python
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
IMAGE = "traceviz:test"
pytestmark = pytest.mark.slow


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], capture_output=True, text=True, **kwargs)


@pytest.fixture(scope="module")
def image():
    build = docker("build", "-t", IMAGE, str(ROOT), timeout=1200)
    assert build.returncode == 0, build.stderr[-3000:]
    return IMAGE


def run_args(data: Path) -> list[str]:
    return ["run", "--rm", "--init", "--network", "host", "-v", f"{data}:/data"]


def test_cli_trace_in_container_with_baked_geo(image, tmp_path):
    result = docker(*run_args(tmp_path), image, "trace", "1.1.1.1", "--cycles", "2", "--json", timeout=180)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["destination_reached"] is True and data["hops"][-1]["ip"] == "1.1.1.1"
    assert any(h["geo"] and h["geo"]["status"] == "geo" for h in data["hops"])


def test_server_in_container_serves_ui_and_reports_ready(image, tmp_path):
    name = f"traceviz-test-{os.getpid()}"
    started = docker("run", "-d", "--rm", "--init", "--name", name, "--network", "host",
                     "-v", f"{tmp_path}:/data", image, "serve", "--port", "18080", timeout=60)
    assert started.returncode == 0, started.stderr
    try:
        health = None
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:18080/api/health", timeout=2) as r:
                    health = json.load(r)
                break
            except OSError:
                time.sleep(0.5)
        assert health is not None, "server never answered /api/health"
        assert health["probe_ok"] is True and health["geo_available"] is True
        with urllib.request.urlopen("http://127.0.0.1:18080/", timeout=5) as r:
            assert '<div id="root">' in r.read().decode()
    finally:
        assert docker("stop", name, timeout=60).returncode == 0


def test_docker_stop_saves_a_running_monitor(image, tmp_path):
    name = f"traceviz-mon-{os.getpid()}"
    started = docker("run", "-d", "--init", "--name", name, "--network", "host",
                     "-v", f"{tmp_path}:/data", image, "monitor", "1.1.1.1", timeout=60)
    assert started.returncode == 0, started.stderr
    try:
        time.sleep(5)
        assert docker("stop", name, timeout=60).returncode == 0
        assert docker("wait", name, timeout=30).stdout.strip() == "0"
    finally:
        docker("rm", "-f", name, timeout=30)
    history = docker(*run_args(tmp_path), image, "history", "--json", timeout=60)
    assert [r["status"] for r in json.loads(history.stdout)] == ["stopped"]
```

Run: `uv run pytest -m slow tests/integration/test_docker.py -q`
Expected: FAIL — the image fixture's build fails (`failed to read dockerfile`).

- [ ] **Step 2: Write the image** 

`.dockerignore`:
```
.git
.venv
.claude
.superpowers
.pytest_cache
**/__pycache__
frontend/node_modules
frontend/dist
data
docs
*.db
*.db-wal
*.db-shm
*.mmdb
```

`Dockerfile`:
```dockerfile
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
```

`compose.yaml` (Linux):
```yaml
# Linux: host networking so traces start from this machine, not a container NAT hop.
# The UI listens on 127.0.0.1 only: http://127.0.0.1:8080
services:
  traceviz:
    build: .
    image: traceviz:latest
    network_mode: host
    init: true
    command: ["serve", "--host", "127.0.0.1", "--port", "8080"]
    volumes:
      - ./data:/data
    restart: unless-stopped
```

`compose.desktop.yaml` (Mac/Windows override):
```yaml
# Docker Desktop (Mac/Windows): host networking isn't the real host there, so publish the
# port on loopback instead. The first one or two hops are Docker's VM and show as "local".
#   docker compose -f compose.yaml -f compose.desktop.yaml up
services:
  traceviz:
    network_mode: !reset null
    ports:
      - "127.0.0.1:8080:8080"
    command: ["serve", "--host", "0.0.0.0", "--port", "8080",
              "--trusted-host", "localhost", "--trusted-host", "127.0.0.1"]
```

- [ ] **Step 3: Build and run the container tests**

Run: `uv run pytest -m slow tests/integration/test_docker.py -q`
Expected: 3 passed (first build downloads base images and DB-IP; allow several minutes).

Also check the compose files parse: `docker compose config -q && docker compose -f compose.yaml -f compose.desktop.yaml config -q`
Expected: no output, exit 0.

- [ ] **Step 4: Document** — in `README.md`, insert before `## Web UI`:

````markdown
## Docker

Everything (web UI, CLI, mtr, geolocation data) is in one image.

**Linux** — host networking, UI on http://127.0.0.1:8080:
```bash
docker compose up -d --build
```

**Mac / Windows (Docker Desktop):**
```bash
docker compose -f compose.yaml -f compose.desktop.yaml up -d --build
```
On Docker Desktop the first hop or two belong to Docker's VM and show as `local`.

**CLI in the container:**
```bash
docker run --rm -it --init --network host -v ./data:/data traceviz trace google.com
docker run --rm -it --init --network host -v ./data:/data traceviz monitor 1.1.1.1
docker run --rm --init --network host -v ./data:/data traceviz history
```
History is shared with the web UI through `./data`. `docker stop` saves running sessions.
If a runtime drops the NET_RAW capability, add `--cap-add NET_RAW`.
````

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore compose.yaml compose.desktop.yaml tests/integration/test_docker.py README.md
git commit -m "feat: Docker image with baked UI and geo data; compose for Linux and Docker Desktop"
```
