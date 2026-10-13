# traceviz Plan 1: Core + CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working `traceviz` Python package whose core (probe, geo, sessions, store) powers `traceviz trace|monitor|history|doctor|fetch-geo` terminal commands, persisting results to SQLite.

**Architecture:** `mtr --raw` is wrapped by `MtrEngine`, which yields `HopEvent`s. `SessionManager` folds them into a `TraceState` (with geo enrichment from offline DB-IP Lite databases), publishes snapshots to subscribers, and persists via `TraceRepository`. The Typer CLI is a thin front-end over `SessionManager`; the web UI (Plan 2) and TUI (Plan 3) will reuse the same core.

**Tech Stack:** Python ≥3.12, uv, Typer, Rich, SQLModel (SQLite), maxminddb, httpx; pytest, pytest-asyncio, respx.

**Spec:** `docs/superpowers/specs/2026-10-13-traceviz-design.md`

## Scope of this plan (phase 1 of 5)

This plan implements spec build-order steps 1–2 (core + CLI). Later plans, each written against the interfaces produced here:
- **Plan 2:** Web API (FastAPI REST + WebSocket) + React UI with world map.
- **Plan 3:** Textual TUI + Braille world map (the map renderer is also added to CLI `trace` output then).
- **Plan 4:** Speed test (core + all front-ends), history charts, `route_diff`, scheduled tests.
- **Plan 5:** Docker packaging (multi-stage image, compose files, slow integration test in-container).

**Spec deltas (decided while planning, consistent with the spec's intent):**
- `HopEvent` is a tagged event (`sent | host | reply | dns`) mirroring `mtr --raw` records; loss is computed as `(sent - received) / sent` per hop in `TraceState`.
- `GeoLookup` is tested with in-memory fake readers using the real DB-IP/MaxMind record shape instead of a generated `.mmdb` (no writer dependency).
- The startup self-check lives in `traceviz doctor` (and `serve` in Plan 2); trace/monitor surface the same actionable message when mtr fails.
- Trace timeout (default 300 s) applies to `trace` sessions; `monitor` sessions run until stopped.
- `monitor` has no `--json` mode in v1.

## Global Constraints

- Python `>=3.12`; package name `traceviz`; console script `traceviz`; src layout `src/traceviz/`.
- `mtr` (mtr-tiny ≥0.93) is invoked **only** with an argument list (never a shell), with `--` before the target, and only with a validated, pre-resolved IP.
- Hop indices are 0-based internally (as mtr reports them) and displayed 1-based (`hop = index + 1`).
- Data dir: `$TRACEVIZ_DATA_DIR` or `~/.local/share/traceviz`; DB at `<data_dir>/traceviz.db`; geo dir `$TRACEVIZ_GEO_DIR` or `<data_dir>/geo`.
- Geo DB filenames: `dbip-city-lite.mmdb`, `dbip-asn-lite.mmdb`. Attribution text: `IP geolocation by DB-IP (https://db-ip.com), licensed CC BY 4.0`.
- Non-global IPs (private, CGNAT 100.64/10, loopback, link-local, ULA) are `local` and are never looked up or plotted.
- SQLite in WAL mode, `PRAGMA user_version = 1`.
- Max 3 concurrent sessions per `SessionManager`; monitor samples flushed every 10 s.
- All commands are run from the repo root with `uv run …`.

## Review Focus

1. **Destination answering at several TTLs, out of order** (real mtr does this; see fixture hops 8–14) → the hop list must stop at the *first* index whose IP is the destination. Pinned in Task 4.
2. **Option-like or shell-ish targets** (`--help`, `-c 1`, `a;rm -rf /`, empty) → rejected before mtr is spawned; argv always has `--`. Pinned in Tasks 2 and 3.
3. **User interrupts mid-run** (Ctrl-C, last subscriber leaves, `stop()`) → mtr child is killed and partial results are saved with status `stopped`. Pinned in Tasks 3 and 8.
4. **mtr fails quietly** (exit 0 with only stderr, or permission denied) → session `failed` with an actionable message, never "completed with 0 hops". Pinned in Tasks 3, 8, 9.
5. **Private/CGNAT/IPv6 link-local hops and a missing geo DB** → hops shown as `local`/`unknown location`, the app still works. Pinned in Tasks 5 and 9.

---

## File Structure

```
pyproject.toml                         project + tool config
.gitignore
README.md                              usage + attribution (Task 10)
src/traceviz/
  __init__.py
  __main__.py                          `python -m traceviz`
  config.py                            Settings (paths from env)
  core/__init__.py
  core/probe/__init__.py
  core/probe/events.py                 HopEvent dataclass
  core/probe/parser.py                 parse_line(): mtr --raw line -> HopEvent
  core/probe/target.py                 resolve_target(): validation + DNS
  core/probe/engine.py                 ProbeEngine protocol, MtrEngine, ProbeError
  core/geo/__init__.py
  core/geo/lookup.py                   GeoResult, GeoLookup
  core/geo/download.py                 download_latest() DB-IP Lite fetcher
  core/sessions/__init__.py
  core/sessions/state.py               HopStats, TraceState (pure aggregation)
  core/sessions/manager.py             SessionManager (orchestration, pub/sub)
  core/store/__init__.py
  core/store/models.py                 SQLModel tables
  core/store/repo.py                   init_db(), TraceRepository
  cli/__init__.py
  cli/render.py                        Rich table rendering of TraceState
  cli/app.py                           Typer commands
tests/
  __init__.py
  fakes.py                             FakeEngine, DictReader, fixture loader
  fixtures/mtr_raw_cloudflare.txt      real `mtr --raw -c 3 1.1.1.1` capture (committed)
  fixtures/fake_mtr.py                 stand-in mtr executable for engine tests
  core/__init__.py
  core/test_parser.py
  core/test_target.py
  core/test_engine.py
  core/test_state.py
  core/test_geo_lookup.py
  core/test_geo_download.py
  core/test_store.py
  core/test_manager.py
  cli/__init__.py
  cli/test_render.py
  cli/test_app.py
  integration/__init__.py
  integration/test_real_mtr.py         @slow
```

**Fixture facts** (`tests/fixtures/mtr_raw_cloudflare.txt`, already committed): record counts `x`=33, `h`=26, `p`=27, `d`=13. Hops 0–3, 5, 7 are routers; 4 and 6 never reply; destination `1.1.1.1` first appears at index 8 and again at 9–14. Hop 0: IP `10.100.0.1`, 3 sent, 3 replies in file order 902.388, 1847.652, 1191.991 ms.

---

### Task 1: Project scaffold + mtr raw parser

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/traceviz/__init__.py`, `src/traceviz/core/__init__.py`, `src/traceviz/core/probe/__init__.py`, `src/traceviz/core/probe/events.py`, `src/traceviz/core/probe/parser.py`, `tests/__init__.py`, `tests/core/__init__.py`
- Test: `tests/core/test_parser.py`

**Interfaces:**
- Produces: `HopEvent(kind: Literal["sent","host","reply","dns"], index: int, ip: str|None=None, rtt_ms: float|None=None, hostname: str|None=None)` (frozen); `parse_line(line: str) -> HopEvent | None`.

- [ ] **Step 1: Create project files**

`pyproject.toml`:
```toml
[project]
name = "traceviz"
version = "0.1.0"
description = "Visual traceroute, route monitor and speed test"
requires-python = ">=3.12"
dependencies = [
    "typer>=0.12",
    "rich>=13.7",
    "sqlmodel>=0.0.22",
    "maxminddb>=2.6",
    "httpx>=0.27",
]

[project.scripts]
traceviz = "traceviz.cli.app:app"

[dependency-groups]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "respx>=0.21"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/traceviz"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
pythonpath = ["."]
markers = ["slow: needs real mtr and network access"]
addopts = "-m 'not slow'"
```

`.gitignore`:
```
__pycache__/
*.pyc
.venv/
.pytest_cache/
*.db
*.db-wal
*.db-shm
*.mmdb
node_modules/
dist/
```

Empty files: `src/traceviz/__init__.py`, `src/traceviz/core/__init__.py`, `src/traceviz/core/probe/__init__.py`, `tests/__init__.py`, `tests/core/__init__.py`.

Run: `uv sync`
Expected: creates `.venv`, installs deps without error.

- [ ] **Step 2: Write the failing test** — `tests/core/test_parser.py`

```python
from collections import Counter
from pathlib import Path

import pytest

from traceviz.core.probe.events import HopEvent
from traceviz.core.probe.parser import parse_line

FIXTURE = Path(__file__).parents[1] / "fixtures" / "mtr_raw_cloudflare.txt"


def test_sent_record():
    assert parse_line("x 3 33003\n") == HopEvent("sent", 3)


def test_host_record():
    assert parse_line("h 0 10.100.0.1") == HopEvent("host", 0, ip="10.100.0.1")


def test_reply_record_converts_microseconds_to_ms():
    assert parse_line("p 2 550805 33002") == HopEvent("reply", 2, rtt_ms=550.805)


def test_dns_record():
    assert parse_line("d 9 one.one.one.one") == HopEvent("dns", 9, hostname="one.one.one.one")


@pytest.mark.parametrize(
    "line", ["", "\n", "m 3 1234", "x", "x abc 1", "p 1 notanumber 2", "garbage line here"]
)
def test_unknown_or_malformed_lines_are_ignored(line):
    assert parse_line(line) is None


def test_parses_real_fixture():
    events = [parse_line(line) for line in FIXTURE.read_text().splitlines()]
    kinds = Counter(e.kind for e in events if e is not None)
    assert kinds == {"sent": 33, "host": 26, "reply": 27, "dns": 13}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/core/test_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'traceviz.core.probe.events'`

- [ ] **Step 4: Implement** 

`src/traceviz/core/probe/events.py`:
```python
from dataclasses import dataclass
from typing import Literal

EventKind = Literal["sent", "host", "reply", "dns"]


@dataclass(frozen=True, slots=True)
class HopEvent:
    """One observation from the probe engine.

    `index` is the 0-based TTL position as reported by mtr.
    """

    kind: EventKind
    index: int
    ip: str | None = None
    rtt_ms: float | None = None
    hostname: str | None = None
```

`src/traceviz/core/probe/parser.py`:
```python
"""Parser for `mtr --raw` output.

Record formats (mtr 0.93+):
  x <pos> <seq>          probe sent
  h <pos> <ip>           host seen at position
  p <pos> <rtt_us> <seq> reply received, RTT in microseconds
  d <pos> <hostname>     reverse DNS result
Other records (e.g. `m` for MPLS) are ignored.
"""

from traceviz.core.probe.events import HopEvent


def parse_line(line: str) -> HopEvent | None:
    parts = line.split()
    if len(parts) < 3:
        return None
    tag = parts[0]
    try:
        index = int(parts[1])
    except ValueError:
        return None
    match tag:
        case "x":
            return HopEvent("sent", index)
        case "h":
            return HopEvent("host", index, ip=parts[2])
        case "p":
            try:
                rtt_us = int(parts[2])
            except ValueError:
                return None
            return HopEvent("reply", index, rtt_ms=rtt_us / 1000)
        case "d":
            return HopEvent("dns", index, hostname=parts[2])
    return None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/core/test_parser.py -v`
Expected: 12 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .gitignore src tests
git commit -m "feat: project scaffold and mtr raw parser"
```

---

### Task 2: Target validation and resolution

**Files:**
- Create: `src/traceviz/core/probe/target.py`
- Test: `tests/core/test_target.py`

**Interfaces:**
- Produces: `class InvalidTarget(ValueError)`; `@dataclass(frozen=True) ResolvedTarget(target: str, ip: str)`; `resolve_target(target: str, resolver=socket.getaddrinfo) -> ResolvedTarget`. Prefers IPv4 when a hostname has both.

- [ ] **Step 1: Write the failing test** — `tests/core/test_target.py`

```python
import socket

import pytest

from traceviz.core.probe.target import InvalidTarget, ResolvedTarget, resolve_target


def fake_resolver(addrs):
    def resolver(host, port, proto=0):
        if not addrs:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, proto, "", (a, 0))
            for a in addrs
        ]

    return resolver


def test_ipv4_literal_needs_no_dns():
    assert resolve_target("1.1.1.1", resolver=fake_resolver([])) == ResolvedTarget("1.1.1.1", "1.1.1.1")


def test_ipv6_literal():
    assert resolve_target("2606:4700::1111", resolver=fake_resolver([])).ip == "2606:4700::1111"


def test_hostname_prefers_ipv4():
    r = resolve_target(" example.com ", resolver=fake_resolver(["2606:2800::1", "93.184.215.14"]))
    assert r == ResolvedTarget("example.com", "93.184.215.14")


def test_hostname_with_only_ipv6():
    assert resolve_target("v6.example", resolver=fake_resolver(["2001:db8::5"])).ip == "2001:db8::5"


@pytest.mark.parametrize(
    "bad", ["", "   ", "--help", "-c 1", "a;rm -rf /", "-x.com", "exa mple.com", "a" * 64 + ".com", "$(id)"]
)
def test_rejects_invalid_targets(bad):
    with pytest.raises(InvalidTarget):
        resolve_target(bad, resolver=fake_resolver(["1.2.3.4"]))


def test_unresolvable_hostname():
    with pytest.raises(InvalidTarget, match="could not resolve"):
        resolve_target("nonexistent.invalid", resolver=fake_resolver([]))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_target.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'traceviz.core.probe.target'`

- [ ] **Step 3: Implement** — `src/traceviz/core/probe/target.py`

```python
import ipaddress
import re
import socket
from dataclasses import dataclass

_LABEL = r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
_HOSTNAME = re.compile(rf"^(?=.{{1,253}}$){_LABEL}(\.{_LABEL})*\.?$")


class InvalidTarget(ValueError):
    """The target is not a valid hostname/IP or cannot be resolved."""


@dataclass(frozen=True)
class ResolvedTarget:
    target: str
    ip: str


def resolve_target(target: str, resolver=socket.getaddrinfo) -> ResolvedTarget:
    t = target.strip()
    try:
        return ResolvedTarget(t, str(ipaddress.ip_address(t)))
    except ValueError:
        pass
    if not _HOSTNAME.match(t):
        raise InvalidTarget(f"not a valid hostname or IP address: {target!r}")
    try:
        infos = resolver(t, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise InvalidTarget(f"could not resolve {t}: {e.strerror}") from e
    addrs = [info[4][0] for info in infos]
    if not addrs:
        raise InvalidTarget(f"could not resolve {t}: no addresses")
    v4 = [a for a in addrs if ":" not in a]
    return ResolvedTarget(t, (v4 or addrs)[0])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_target.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/traceviz/core/probe/target.py tests/core/test_target.py
git commit -m "feat: validate and resolve trace targets"
```

---

### Task 3: MtrEngine (subprocess wrapper)

**Files:**
- Create: `src/traceviz/core/probe/engine.py`, `tests/fixtures/fake_mtr.py`
- Test: `tests/core/test_engine.py`

**Interfaces:**
- Consumes: `parse_line`, `HopEvent` (Task 1).
- Produces:
  - `ProbeProtocol = Literal["icmp", "udp", "tcp"]`
  - `class ProbeError(RuntimeError)`
  - `class ProbeEngine(typing.Protocol)`: `def run(self, ip: str, protocol: ProbeProtocol = "icmp", max_hops: int = 30, cycles: int | None = 10) -> AsyncIterator[HopEvent]`; `async def self_check(self) -> None` (raises `ProbeError`).
  - `class MtrEngine(command: Sequence[str] = ("mtr",))` implementing it, with `build_argv(...) -> list[str]` and a `running: int` counter of live child processes. `cycles=None` means run until closed.

- [ ] **Step 1: Create the fake mtr** — `tests/fixtures/fake_mtr.py`

```python
"""Stand-in for mtr in tests: fake_mtr.py MODE FIXTURE [ignored mtr args...]

MODE: replay | hang | fail | stderr-only
"""

import sys
import time

mode, fixture = sys.argv[1], sys.argv[2]
if mode == "fail":
    print("mtr: Failure to open IPv4 sockets: Permission denied", file=sys.stderr)
    sys.exit(1)
if mode == "stderr-only":
    print("mtr: Failed to resolve host: x: Name or service not known", file=sys.stderr)
    sys.exit(0)
with open(fixture) as f:
    for line in f:
        print(line, end="", flush=True)
if mode == "hang":
    time.sleep(3600)
```

- [ ] **Step 2: Write the failing test** — `tests/core/test_engine.py`

```python
import sys
from pathlib import Path

import pytest

from traceviz.core.probe.engine import MtrEngine, ProbeError
from traceviz.core.probe.events import HopEvent

FIXTURES = Path(__file__).parents[1] / "fixtures"
FAKE = str(FIXTURES / "fake_mtr.py")
DATA = str(FIXTURES / "mtr_raw_cloudflare.txt")


def fake_engine(mode: str) -> MtrEngine:
    return MtrEngine(command=(sys.executable, FAKE, mode, DATA))


def test_argv_icmp_with_cycles():
    argv = MtrEngine().build_argv("1.1.1.1", "icmp", 30, 10)
    assert argv == ["mtr", "--raw", "-m", "30", "-c", "10", "--", "1.1.1.1"]


def test_argv_udp_unlimited_cycles():
    argv = MtrEngine().build_argv("1.1.1.1", "udp", 20, None)
    assert argv == ["mtr", "--raw", "-m", "20", "-u", "--", "1.1.1.1"]


def test_argv_tcp_uses_port_443():
    argv = MtrEngine().build_argv("2606:4700::1111", "tcp", 30, 5)
    assert argv == ["mtr", "--raw", "-m", "30", "-c", "5", "-T", "-P", "443", "--", "2606:4700::1111"]


def test_argv_target_always_after_double_dash():
    argv = MtrEngine().build_argv("--help", "icmp", 30, 1)
    assert argv[-2:] == ["--", "--help"]


async def test_replays_events():
    events = [e async for e in fake_engine("replay").run("1.1.1.1")]
    assert len(events) == 99
    assert events[0] == HopEvent("sent", 0)


async def test_nonzero_exit_raises_with_permission_hint():
    with pytest.raises(ProbeError, match="NET_RAW"):
        async for _ in fake_engine("fail").run("1.1.1.1"):
            pass


async def test_stderr_without_events_is_an_error_even_on_exit_zero():
    with pytest.raises(ProbeError, match="Failed to resolve"):
        async for _ in fake_engine("stderr-only").run("1.1.1.1"):
            pass


async def test_closing_early_kills_the_process():
    engine = fake_engine("hang")
    gen = engine.run("1.1.1.1", cycles=None)
    seen = [await anext(gen) for _ in range(5)]
    assert len(seen) == 5 and engine.running == 1
    await gen.aclose()
    assert engine.running == 0


async def test_missing_binary_is_probe_error():
    with pytest.raises(ProbeError, match="not found"):
        async for _ in MtrEngine(command=("definitely-not-mtr-xyz",)).run("1.1.1.1"):
            pass


async def test_self_check_reports_failure():
    with pytest.raises(ProbeError, match="NET_RAW"):
        await fake_engine("fail").self_check()


async def test_self_check_passes():
    await fake_engine("replay").self_check()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/core/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'traceviz.core.probe.engine'`

- [ ] **Step 4: Implement** — `src/traceviz/core/probe/engine.py`

```python
import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Literal, Protocol

from traceviz.core.probe.events import HopEvent
from traceviz.core.probe.parser import parse_line

ProbeProtocol = Literal["icmp", "udp", "tcp"]

_PROTOCOL_FLAGS: dict[str, list[str]] = {"icmp": [], "udp": ["-u"], "tcp": ["-T", "-P", "443"]}
_PERMISSION_MARKERS = ("Permission denied", "Failure to open", "Operation not permitted")
_PERMISSION_HINT = (
    "mtr could not open raw sockets. In Docker run with --cap-add NET_RAW; "
    "on a Linux host run: sudo setcap cap_net_raw+ep $(command -v mtr-packet)"
)


class ProbeError(RuntimeError):
    """The probe engine could not run or exited abnormally."""


class ProbeEngine(Protocol):
    def run(
        self, ip: str, protocol: ProbeProtocol = "icmp", max_hops: int = 30, cycles: int | None = 10
    ) -> AsyncIterator[HopEvent]: ...

    async def self_check(self) -> None: ...


def _explain(stderr: str) -> str:
    if any(m in stderr for m in _PERMISSION_MARKERS):
        return f"{stderr}\n{_PERMISSION_HINT}"
    return stderr


class MtrEngine:
    def __init__(self, command: Sequence[str] = ("mtr",)) -> None:
        self.command = list(command)
        self.running = 0

    def build_argv(
        self, ip: str, protocol: ProbeProtocol, max_hops: int, cycles: int | None
    ) -> list[str]:
        argv = [*self.command, "--raw", "-m", str(max_hops)]
        if cycles is not None:
            argv += ["-c", str(cycles)]
        argv += _PROTOCOL_FLAGS[protocol]
        return [*argv, "--", ip]

    async def run(
        self, ip: str, protocol: ProbeProtocol = "icmp", max_hops: int = 30, cycles: int | None = 10
    ) -> AsyncIterator[HopEvent]:
        argv = self.build_argv(ip, protocol, max_hops, cycles)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError as e:
            raise ProbeError(f"{argv[0]} not found — install mtr (package mtr-tiny)") from e
        self.running += 1
        got_event = False
        try:
            assert proc.stdout is not None and proc.stderr is not None
            async for raw in proc.stdout:
                event = parse_line(raw.decode(errors="replace"))
                if event is not None:
                    got_event = True
                    yield event
            returncode = await proc.wait()
            stderr = (await proc.stderr.read()).decode(errors="replace").strip()
            if returncode != 0 or (stderr and not got_event):
                raise ProbeError(_explain(stderr or f"mtr exited with code {returncode}"))
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            self.running -= 1

    async def self_check(self) -> None:
        async for _ in self.run("127.0.0.1", max_hops=1, cycles=1):
            pass
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/core/test_engine.py -v`
Expected: all passed (the `hang` test finishes in well under a second)

- [ ] **Step 6: Commit**

```bash
git add src/traceviz/core/probe/engine.py tests/fixtures/fake_mtr.py tests/core/test_engine.py
git commit -m "feat: MtrEngine wraps mtr --raw with cleanup and actionable errors"
```

---

### Task 4: TraceState aggregation

**Files:**
- Create: `src/traceviz/core/geo/__init__.py`, `src/traceviz/core/geo/lookup.py` (only the `GeoResult` dataclass in this task; `GeoLookup` comes in Task 5), `src/traceviz/core/sessions/__init__.py`, `src/traceviz/core/sessions/state.py`, `tests/fakes.py`
- Test: `tests/core/test_state.py`

**Interfaces:**
- Consumes: `HopEvent`, `parse_line`.
- Produces:
  - `GeoResult(status: Literal["geo","local","unknown"], lat=None, lon=None, city=None, country=None, country_name=None, asn: int|None=None, org=None, approximate: bool=False)` (frozen dataclass) in `traceviz.core.geo.lookup`.
  - `HopStats` dataclass: fields `index, ip, hostname, sent, received, last_ms, best_ms, worst_ms, sum_ms, jitter_sum_ms, geo: GeoResult|None`; properties `avg_ms`, `jitter_ms`, `loss_pct`; methods `record_rtt(rtt_ms)`, `to_dict()`.
  - `TraceState` dataclass: `target, target_ip, protocol, kind: Literal["trace","monitor"], status: Literal["running","completed","failed","stopped"]="running", error: str|None=None, hops_by_index: dict[int, HopStats]`; `apply(event) -> HopStats`; properties `destination_index`, `hops`, `suggest_other_protocol`; `snapshot() -> TraceState`; `to_dict() -> dict`.
  - `tests/fakes.py`: `fixture_events() -> list[HopEvent]`.

- [ ] **Step 1: Write `GeoResult`** — `src/traceviz/core/geo/lookup.py` (empty `src/traceviz/core/geo/__init__.py` and `src/traceviz/core/sessions/__init__.py` too)

```python
from dataclasses import dataclass
from typing import Literal

GeoStatus = Literal["geo", "local", "unknown"]


@dataclass(frozen=True)
class GeoResult:
    status: GeoStatus
    lat: float | None = None
    lon: float | None = None
    city: str | None = None
    country: str | None = None
    country_name: str | None = None
    asn: int | None = None
    org: str | None = None
    approximate: bool = False
```

- [ ] **Step 2: Write test helper** — `tests/fakes.py`

```python
from pathlib import Path

from traceviz.core.probe.events import HopEvent
from traceviz.core.probe.parser import parse_line

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_events() -> list[HopEvent]:
    lines = (FIXTURES / "mtr_raw_cloudflare.txt").read_text().splitlines()
    return [e for e in map(parse_line, lines) if e is not None]
```

- [ ] **Step 3: Write the failing test** — `tests/core/test_state.py`

```python
import pytest

from tests.fakes import fixture_events
from traceviz.core.geo.lookup import GeoResult
from traceviz.core.probe.events import HopEvent
from traceviz.core.sessions.state import TraceState


def new_state(target_ip="1.1.1.1", kind="trace"):
    return TraceState(target="1.1.1.1", target_ip=target_ip, protocol="icmp", kind=kind)


def replay(state, events):
    for e in events:
        state.apply(e)
    return state


def test_hop_zero_statistics_from_real_capture():
    hop = replay(new_state(), fixture_events()).hops_by_index[0]
    assert hop.ip == "10.100.0.1"
    assert hop.hostname == "_gateway"
    assert (hop.sent, hop.received) == (3, 3)
    assert hop.last_ms == pytest.approx(1191.991)
    assert hop.best_ms == pytest.approx(902.388)
    assert hop.worst_ms == pytest.approx(1847.652)
    assert hop.avg_ms == pytest.approx(1314.010333, rel=1e-6)
    # mean absolute difference of consecutive RTTs: (945.264 + 655.661) / 2
    assert hop.jitter_ms == pytest.approx(800.4625)
    assert hop.loss_pct == 0.0


def test_hops_stop_at_first_destination_index_despite_out_of_order_replies():
    state = replay(new_state(), fixture_events())
    assert state.destination_index == 8
    assert [h.index for h in state.hops] == list(range(9))


def test_silent_hops_are_kept_with_full_loss():
    state = replay(new_state(), fixture_events())
    silent = [h for h in state.hops if h.ip is None]
    assert [h.index for h in silent] == [4, 6]
    assert all(h.loss_pct == 100.0 and h.avg_ms is None for h in silent)


def test_trailing_silent_hops_trimmed_when_destination_not_reached():
    state = replay(
        new_state(target_ip="9.9.9.9"),
        [HopEvent("sent", 0), HopEvent("host", 0, ip="10.0.0.1"), HopEvent("reply", 0, rtt_ms=1.0),
         HopEvent("sent", 1), HopEvent("sent", 2)],
    )
    assert [h.index for h in state.hops] == [0]
    state.status = "completed"
    assert state.suggest_other_protocol is True


def test_no_protocol_suggestion_while_running_or_when_reached():
    running = replay(new_state(target_ip="9.9.9.9"), [HopEvent("sent", 0)])
    assert running.suggest_other_protocol is False
    done = replay(new_state(), fixture_events())
    done.status = "completed"
    assert done.suggest_other_protocol is False


def test_new_ip_at_same_hop_clears_geo():
    state = new_state()
    hop = state.apply(HopEvent("host", 2, ip="8.8.8.8"))
    hop.geo = GeoResult("geo", lat=1.0, lon=2.0)
    state.apply(HopEvent("host", 2, ip="8.8.8.8"))
    assert hop.geo is not None
    state.apply(HopEvent("host", 2, ip="8.8.4.4"))
    assert hop.ip == "8.8.4.4" and hop.geo is None


def test_unsent_hop_has_zero_loss():
    hop = new_state().apply(HopEvent("host", 0, ip="10.0.0.1"))
    assert hop.loss_pct == 0.0


def test_snapshot_is_independent_copy():
    state = replay(new_state(), fixture_events())
    snap = state.snapshot()
    state.apply(HopEvent("sent", 0))
    assert snap.hops_by_index[0].sent == 3


def test_to_dict_uses_one_based_hop_numbers():
    state = replay(new_state(), fixture_events())
    state.hops_by_index[8].geo = GeoResult("geo", lat=-33.9, lon=151.2, city="Sydney", country="AU",
                                           asn=13335, org="Cloudflare", approximate=True)
    d = state.to_dict()
    assert d["destination_reached"] is True
    assert [h["hop"] for h in d["hops"]] == list(range(1, 10))
    assert d["hops"][8]["geo"]["city"] == "Sydney"
    assert d["hops"][4]["ip"] is None and d["hops"][4]["loss_pct"] == 100.0
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/core/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'traceviz.core.sessions.state'`

- [ ] **Step 5: Implement** — `src/traceviz/core/sessions/state.py`

```python
import copy
from dataclasses import asdict, dataclass, field
from typing import Literal

from traceviz.core.geo.lookup import GeoResult
from traceviz.core.probe.events import HopEvent

SessionKind = Literal["trace", "monitor"]
SessionStatus = Literal["running", "completed", "failed", "stopped"]


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 3)


@dataclass
class HopStats:
    index: int
    ip: str | None = None
    hostname: str | None = None
    sent: int = 0
    received: int = 0
    last_ms: float | None = None
    best_ms: float | None = None
    worst_ms: float | None = None
    sum_ms: float = 0.0
    jitter_sum_ms: float = 0.0
    geo: GeoResult | None = None

    def record_rtt(self, rtt_ms: float) -> None:
        if self.last_ms is not None:
            self.jitter_sum_ms += abs(rtt_ms - self.last_ms)
        self.received += 1
        self.sum_ms += rtt_ms
        self.last_ms = rtt_ms
        self.best_ms = rtt_ms if self.best_ms is None else min(self.best_ms, rtt_ms)
        self.worst_ms = rtt_ms if self.worst_ms is None else max(self.worst_ms, rtt_ms)

    @property
    def avg_ms(self) -> float | None:
        return self.sum_ms / self.received if self.received else None

    @property
    def jitter_ms(self) -> float | None:
        return self.jitter_sum_ms / (self.received - 1) if self.received > 1 else None

    @property
    def loss_pct(self) -> float:
        if not self.sent:
            return 0.0
        return max(0.0, 100.0 * (self.sent - self.received) / self.sent)

    def to_dict(self) -> dict:
        return {
            "hop": self.index + 1,
            "ip": self.ip,
            "hostname": self.hostname,
            "sent": self.sent,
            "received": self.received,
            "loss_pct": round(self.loss_pct, 1),
            "last_ms": _r(self.last_ms),
            "avg_ms": _r(self.avg_ms),
            "best_ms": _r(self.best_ms),
            "worst_ms": _r(self.worst_ms),
            "jitter_ms": _r(self.jitter_ms),
            "geo": asdict(self.geo) if self.geo else None,
        }


@dataclass
class TraceState:
    target: str
    target_ip: str
    protocol: str
    kind: SessionKind
    status: SessionStatus = "running"
    error: str | None = None
    hops_by_index: dict[int, HopStats] = field(default_factory=dict)

    def apply(self, event: HopEvent) -> HopStats:
        hop = self.hops_by_index.setdefault(event.index, HopStats(event.index))
        match event.kind:
            case "sent":
                hop.sent += 1
            case "host":
                if hop.ip != event.ip:
                    hop.ip = event.ip
                    hop.geo = None
            case "dns":
                hop.hostname = event.hostname
            case "reply":
                assert event.rtt_ms is not None
                hop.record_rtt(event.rtt_ms)
        return hop

    @property
    def destination_index(self) -> int | None:
        found = [i for i, h in self.hops_by_index.items() if h.ip == self.target_ip]
        return min(found) if found else None

    @property
    def hops(self) -> list[HopStats]:
        ordered = [self.hops_by_index[i] for i in sorted(self.hops_by_index)]
        dest = self.destination_index
        if dest is not None:
            return [h for h in ordered if h.index <= dest]
        last_seen = max((h.index for h in ordered if h.ip), default=-1)
        return [h for h in ordered if h.index <= last_seen]

    @property
    def suggest_other_protocol(self) -> bool:
        if self.status == "running" or self.destination_index is not None:
            return False
        return not any(h.ip for h in self.hops_by_index.values() if h.index >= 1)

    def snapshot(self) -> "TraceState":
        return copy.deepcopy(self)

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "target_ip": self.target_ip,
            "protocol": self.protocol,
            "kind": self.kind,
            "status": self.status,
            "error": self.error,
            "destination_reached": self.destination_index is not None,
            "hops": [h.to_dict() for h in self.hops],
        }
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/core/test_state.py -v`
Expected: all passed

- [ ] **Step 7: Commit**

```bash
git add src/traceviz/core/geo src/traceviz/core/sessions tests/fakes.py tests/core/test_state.py
git commit -m "feat: per-hop trace aggregation with destination truncation"
```

---

### Task 5: GeoLookup

**Files:**
- Modify: `src/traceviz/core/geo/lookup.py` (append below `GeoResult`)
- Modify: `tests/fakes.py` (append `DictReader`)
- Test: `tests/core/test_geo_lookup.py`

**Interfaces:**
- Consumes: `GeoResult` (Task 4).
- Produces: `CITY_DB = "dbip-city-lite.mmdb"`, `ASN_DB = "dbip-asn-lite.mmdb"`, `ANYCAST_ASNS: frozenset[int]`; `class GeoLookup(city: Reader|None, asn: Reader|None)` with `GeoLookup.open(geo_dir: Path) -> GeoLookup`, `.available -> bool`, `.lookup(ip: str) -> GeoResult`. `Reader` is any object with `get(ip: str) -> dict | None` (maxminddb readers satisfy it). `tests/fakes.py`: `DictReader(data: dict[str, dict])`.

- [ ] **Step 1: Append test helper** to `tests/fakes.py`

```python
class DictReader:
    """In-memory stand-in for a maxminddb Reader."""

    def __init__(self, data: dict[str, dict]):
        self.data = data

    def get(self, ip: str) -> dict | None:
        return self.data.get(ip)
```

- [ ] **Step 2: Write the failing test** — `tests/core/test_geo_lookup.py`

```python
import pytest

from tests.fakes import DictReader
from traceviz.core.geo.lookup import GeoLookup, GeoResult

CITY = {
    "8.8.8.8": {
        "city": {"names": {"en": "Mountain View"}},
        "country": {"iso_code": "US", "names": {"en": "United States"}},
        "location": {"latitude": 37.386, "longitude": -122.0838},
    },
    "81.2.69.160": {
        "city": {"names": {"en": "London"}},
        "country": {"iso_code": "GB", "names": {"en": "United Kingdom"}},
        "location": {"latitude": 51.5142, "longitude": -0.0931},
    },
    "45.127.172.45": {
        "country": {"iso_code": "AU", "names": {"en": "Australia"}},
        "location": {"latitude": -33.494, "longitude": 143.2104},
    },
}
ASN = {
    "8.8.8.8": {"autonomous_system_number": 15169, "autonomous_system_organization": "Google LLC"},
    "81.2.69.160": {"autonomous_system_number": 20712, "autonomous_system_organization": "Andrews & Arnold"},
    "5.5.5.5": {"autonomous_system_number": 6805, "autonomous_system_organization": "Telefonica"},
}


@pytest.fixture
def geo():
    return GeoLookup(city=DictReader(CITY), asn=DictReader(ASN))


@pytest.mark.parametrize(
    "ip", ["10.0.0.1", "192.168.65.3", "100.64.0.8", "127.0.0.1", "169.254.1.1", "fe80::1", "fd00::1"]
)
def test_non_global_addresses_are_local(geo, ip):
    assert geo.lookup(ip) == GeoResult("local")


def test_city_level_result(geo):
    r = geo.lookup("81.2.69.160")
    assert r == GeoResult("geo", 51.5142, -0.0931, "London", "GB", "United Kingdom", 20712,
                          "Andrews & Arnold", approximate=False)


def test_anycast_asn_is_approximate(geo):
    r = geo.lookup("8.8.8.8")
    assert r.status == "geo" and r.city == "Mountain View" and r.asn == 15169 and r.approximate


def test_country_only_result_is_approximate(geo):
    r = geo.lookup("45.127.172.45")
    assert r.status == "geo" and r.city is None and r.country == "AU" and r.approximate


def test_unknown_location_keeps_asn(geo):
    assert geo.lookup("5.5.5.5") == GeoResult("unknown", asn=6805, org="Telefonica")


def test_unknown_everything(geo):
    assert geo.lookup("1.0.0.1") == GeoResult("unknown")


def test_open_with_missing_files_is_unavailable_but_works(tmp_path):
    geo = GeoLookup.open(tmp_path / "nope")
    assert geo.available is False
    assert geo.lookup("8.8.8.8") == GeoResult("unknown")
    assert geo.lookup("10.0.0.1") == GeoResult("local")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/core/test_geo_lookup.py -v`
Expected: FAIL — `ImportError: cannot import name 'GeoLookup'`

- [ ] **Step 4: Implement** — append to `src/traceviz/core/geo/lookup.py` (and add `import ipaddress`, `from pathlib import Path`, `from typing import Protocol` to the imports at the top)

```python
CITY_DB = "dbip-city-lite.mmdb"
ASN_DB = "dbip-asn-lite.mmdb"

# Networks whose addresses are anycast: geolocation shows one of many sites.
ANYCAST_ASNS = frozenset({13335, 15169, 16509, 8075, 20940, 54113})


class Reader(Protocol):
    def get(self, ip: str) -> dict | None: ...


def _open_reader(path: Path) -> Reader | None:
    if not path.is_file():
        return None
    import maxminddb

    return maxminddb.open_database(str(path))


class GeoLookup:
    def __init__(self, city: Reader | None, asn: Reader | None) -> None:
        self._city = city
        self._asn = asn

    @classmethod
    def open(cls, geo_dir: Path) -> "GeoLookup":
        return cls(_open_reader(geo_dir / CITY_DB), _open_reader(geo_dir / ASN_DB))

    @property
    def available(self) -> bool:
        return self._city is not None

    def lookup(self, ip: str) -> GeoResult:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
        if not addr.is_global:
            return GeoResult("local")
        asn_rec = (self._asn.get(ip) if self._asn else None) or {}
        asn = asn_rec.get("autonomous_system_number")
        org = asn_rec.get("autonomous_system_organization")
        city_rec = (self._city.get(ip) if self._city else None) or {}
        location = city_rec.get("location") or {}
        lat, lon = location.get("latitude"), location.get("longitude")
        if lat is None or lon is None:
            return GeoResult("unknown", asn=asn, org=org)
        city = ((city_rec.get("city") or {}).get("names") or {}).get("en")
        country = city_rec.get("country") or {}
        return GeoResult(
            "geo",
            lat=lat,
            lon=lon,
            city=city,
            country=country.get("iso_code"),
            country_name=(country.get("names") or {}).get("en"),
            asn=asn,
            org=org,
            approximate=city is None or asn in ANYCAST_ASNS,
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/core/test_geo_lookup.py tests/core/test_state.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/traceviz/core/geo/lookup.py tests/fakes.py tests/core/test_geo_lookup.py
git commit -m "feat: offline IP geolocation with local and anycast handling"
```

---

### Task 6: DB-IP Lite downloader

**Files:**
- Create: `src/traceviz/core/geo/download.py`
- Test: `tests/core/test_geo_download.py`

**Interfaces:**
- Consumes: `CITY_DB`, `ASN_DB` (Task 5).
- Produces: `ATTRIBUTION: str`; `class GeoDownloadError(RuntimeError)`; `download_latest(dest: Path, client: httpx.Client, today: date) -> str` — writes both DBs into `dest`, returns the `YYYY-MM` used; falls back to the previous month on HTTP 404.

- [ ] **Step 1: Write the failing test** — `tests/core/test_geo_download.py`

```python
import gzip
from datetime import date

import httpx
import pytest
import respx

from traceviz.core.geo.download import GeoDownloadError, download_latest

URL = "https://download.db-ip.com/free/dbip-{kind}-lite-{month}.mmdb.gz"


def serve(month, status=200):
    for kind in ("city", "asn"):
        respx.get(URL.format(kind=kind, month=month)).respond(
            status, content=gzip.compress(f"{kind}-{month}".encode()) if status == 200 else b""
        )


@respx.mock
def test_downloads_current_month(tmp_path):
    serve("2026-10")
    with httpx.Client() as client:
        month = download_latest(tmp_path / "geo", client, date(2026, 10, 13))
    assert month == "2026-10"
    assert (tmp_path / "geo" / "dbip-city-lite.mmdb").read_bytes() == b"city-2026-10"
    assert (tmp_path / "geo" / "dbip-asn-lite.mmdb").read_bytes() == b"asn-2026-10"


@respx.mock
def test_falls_back_to_previous_month_across_year(tmp_path):
    serve("2027-01", status=404)
    serve("2026-12")
    with httpx.Client() as client:
        assert download_latest(tmp_path, client, date(2027, 1, 2)) == "2026-12"
    assert (tmp_path / "dbip-city-lite.mmdb").read_bytes() == b"city-2026-12"


@respx.mock
def test_gives_up_after_two_missing_months(tmp_path):
    serve("2026-10", status=404)
    serve("2026-09", status=404)
    with httpx.Client() as client, pytest.raises(GeoDownloadError):
        download_latest(tmp_path, client, date(2026, 10, 1))


@respx.mock
def test_server_error_propagates(tmp_path):
    serve("2026-10", status=500)
    with httpx.Client() as client, pytest.raises(httpx.HTTPStatusError):
        download_latest(tmp_path, client, date(2026, 10, 13))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_geo_download.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'traceviz.core.geo.download'`

- [ ] **Step 3: Implement** — `src/traceviz/core/geo/download.py`

```python
import gzip
from datetime import date, timedelta
from pathlib import Path

import httpx

from traceviz.core.geo.lookup import ASN_DB, CITY_DB

ATTRIBUTION = "IP geolocation by DB-IP (https://db-ip.com), licensed CC BY 4.0"
_URL = "https://download.db-ip.com/free/dbip-{kind}-lite-{month}.mmdb.gz"
_FILES = {"city": CITY_DB, "asn": ASN_DB}


class GeoDownloadError(RuntimeError):
    """DB-IP Lite databases could not be downloaded."""


def _previous_month(d: date) -> date:
    return d.replace(day=1) - timedelta(days=1)


def _download_month(dest: Path, client: httpx.Client, month: str) -> None:
    payloads: dict[str, bytes] = {}
    for kind, filename in _FILES.items():
        resp = client.get(_URL.format(kind=kind, month=month), follow_redirects=True)
        resp.raise_for_status()
        payloads[filename] = gzip.decompress(resp.content)
    dest.mkdir(parents=True, exist_ok=True)
    for filename, data in payloads.items():
        tmp = dest / f"{filename}.tmp"
        tmp.write_bytes(data)
        tmp.replace(dest / filename)


def download_latest(dest: Path, client: httpx.Client, today: date) -> str:
    for d in (today, _previous_month(today)):
        month = d.strftime("%Y-%m")
        try:
            _download_month(dest, client, month)
            return month
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise
    raise GeoDownloadError("DB-IP Lite databases are not available for this or last month")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_geo_download.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/traceviz/core/geo/download.py tests/core/test_geo_download.py
git commit -m "feat: download DB-IP Lite databases with month fallback"
```

---

### Task 7: SQLite store

**Files:**
- Create: `src/traceviz/core/store/__init__.py` (empty), `src/traceviz/core/store/models.py`, `src/traceviz/core/store/repo.py`
- Test: `tests/core/test_store.py`

**Interfaces:**
- Consumes: `TraceState`, `HopStats`, `GeoResult`.
- Produces:
  - Tables `TraceRecord` (`traces`), `HopRecord` (`hops`), `MonitorSampleRecord` (`monitor_samples`) — fields below.
  - `SCHEMA_VERSION = 1`; `init_db(path: Path) -> sqlalchemy.Engine` (creates parent dirs, WAL, tables, user_version).
  - `TraceRepository(engine)` with `create_trace(state: TraceState, started_at: datetime) -> int`, `finish_trace(trace_id: int, state: TraceState, finished_at: datetime) -> None` (idempotent), `add_monitor_samples(rows: list[MonitorSampleRecord]) -> None`, `list_traces(target: str|None = None, limit: int = 20) -> list[TraceRecord]` (newest first), `get_trace(trace_id) -> tuple[TraceRecord, list[HopRecord]] | None`, `monitor_samples(trace_id) -> list[MonitorSampleRecord]`.

- [ ] **Step 1: Write the failing test** — `tests/core/test_store.py`

```python
import sqlite3
from datetime import UTC, datetime

import pytest

from tests.fakes import fixture_events
from traceviz.core.geo.lookup import GeoResult
from traceviz.core.sessions.state import TraceState
from traceviz.core.store.models import MonitorSampleRecord
from traceviz.core.store.repo import TraceRepository, init_db

T0 = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 13, 8, 1, tzinfo=UTC)


@pytest.fixture
def repo(tmp_path):
    return TraceRepository(init_db(tmp_path / "nested" / "traceviz.db"))


def finished_state(target="1.1.1.1"):
    state = TraceState(target=target, target_ip="1.1.1.1", protocol="icmp", kind="trace")
    for e in fixture_events():
        state.apply(e)
    state.hops_by_index[8].geo = GeoResult("geo", lat=-33.9, lon=151.2, city="Sydney", country="AU",
                                           country_name="Australia", asn=13335, org="Cloudflare",
                                           approximate=True)
    state.status = "completed"
    return state


def test_init_db_creates_wal_database_with_version(tmp_path):
    path = tmp_path / "a" / "b" / "traceviz.db"
    init_db(path)
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert con.execute("PRAGMA user_version").fetchone()[0] == 1
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"traces", "hops", "monitor_samples"} <= tables


def test_init_db_is_idempotent(tmp_path):
    init_db(tmp_path / "x.db")
    init_db(tmp_path / "x.db")


def test_trace_roundtrip(repo):
    state = finished_state()
    tid = repo.create_trace(state, T0)
    repo.finish_trace(tid, state, T1)
    rec, hops = repo.get_trace(tid)
    assert (rec.target, rec.status, rec.kind, rec.protocol) == ("1.1.1.1", "completed", "trace", "icmp")
    assert rec.finished_at is not None
    assert [h.hop_index for h in hops] == list(range(9))
    assert hops[4].ip is None and hops[4].loss_pct == 100.0
    assert hops[0].avg_ms == pytest.approx(1314.010333, rel=1e-6)
    assert (hops[8].city, hops[8].asn, hops[8].approximate, hops[8].geo_status) == ("Sydney", 13335, True, "geo")


def test_finish_twice_does_not_duplicate_hops(repo):
    state = finished_state()
    tid = repo.create_trace(state, T0)
    repo.finish_trace(tid, state, T1)
    repo.finish_trace(tid, state, T1)
    assert len(repo.get_trace(tid)[1]) == 9


def test_get_missing_trace(repo):
    assert repo.get_trace(999) is None


def test_list_traces_newest_first_with_filter_and_limit(repo):
    ids = [repo.create_trace(finished_state(t), T0) for t in ["a.com", "b.com", "a.com"]]
    assert [r.id for r in repo.list_traces()] == ids[::-1]
    assert [r.id for r in repo.list_traces(target="a.com")] == [ids[2], ids[0]]
    assert len(repo.list_traces(limit=1)) == 1


def test_monitor_samples(repo):
    tid = repo.create_trace(finished_state(), T0)
    repo.add_monitor_samples([
        MonitorSampleRecord(trace_id=tid, ts=T0, hop_index=0, sent=10, received=9, avg_ms=12.5),
        MonitorSampleRecord(trace_id=tid, ts=T1, hop_index=0, sent=10, received=10, avg_ms=11.0),
    ])
    samples = repo.monitor_samples(tid)
    assert [(s.sent, s.received) for s in samples] == [(10, 9), (10, 10)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'traceviz.core.store'`

- [ ] **Step 3: Implement models** — `src/traceviz/core/store/models.py`

```python
from datetime import datetime

from sqlmodel import Field, SQLModel


class TraceRecord(SQLModel, table=True):
    __tablename__ = "traces"

    id: int | None = Field(default=None, primary_key=True)
    target: str = Field(index=True)
    target_ip: str
    protocol: str
    kind: str
    status: str
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class HopRecord(SQLModel, table=True):
    __tablename__ = "hops"

    id: int | None = Field(default=None, primary_key=True)
    trace_id: int = Field(foreign_key="traces.id", index=True)
    hop_index: int
    ip: str | None = None
    hostname: str | None = None
    sent: int
    received: int
    loss_pct: float
    last_ms: float | None = None
    avg_ms: float | None = None
    best_ms: float | None = None
    worst_ms: float | None = None
    jitter_ms: float | None = None
    geo_status: str | None = None
    lat: float | None = None
    lon: float | None = None
    city: str | None = None
    country: str | None = None
    country_name: str | None = None
    asn: int | None = None
    org: str | None = None
    approximate: bool = False


class MonitorSampleRecord(SQLModel, table=True):
    __tablename__ = "monitor_samples"

    id: int | None = Field(default=None, primary_key=True)
    trace_id: int = Field(foreign_key="traces.id", index=True)
    ts: datetime
    hop_index: int
    sent: int
    received: int
    avg_ms: float | None = None
```

- [ ] **Step 4: Implement repository** — `src/traceviz/core/store/repo.py`

```python
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine, select

from traceviz.core.sessions.state import HopStats, TraceState
from traceviz.core.store.models import HopRecord, MonitorSampleRecord, TraceRecord

SCHEMA_VERSION = 1


def init_db(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(f"PRAGMA user_version={SCHEMA_VERSION}")
    return engine


def _hop_record(trace_id: int, hop: HopStats) -> HopRecord:
    geo = hop.geo
    return HopRecord(
        trace_id=trace_id,
        hop_index=hop.index,
        ip=hop.ip,
        hostname=hop.hostname,
        sent=hop.sent,
        received=hop.received,
        loss_pct=hop.loss_pct,
        last_ms=hop.last_ms,
        avg_ms=hop.avg_ms,
        best_ms=hop.best_ms,
        worst_ms=hop.worst_ms,
        jitter_ms=hop.jitter_ms,
        geo_status=geo.status if geo else None,
        lat=geo.lat if geo else None,
        lon=geo.lon if geo else None,
        city=geo.city if geo else None,
        country=geo.country if geo else None,
        country_name=geo.country_name if geo else None,
        asn=geo.asn if geo else None,
        org=geo.org if geo else None,
        approximate=geo.approximate if geo else False,
    )


class TraceRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_trace(self, state: TraceState, started_at: datetime) -> int:
        rec = TraceRecord(
            target=state.target,
            target_ip=state.target_ip,
            protocol=state.protocol,
            kind=state.kind,
            status=state.status,
            started_at=started_at,
        )
        with Session(self.engine) as db:
            db.add(rec)
            db.commit()
            db.refresh(rec)
            assert rec.id is not None
            return rec.id

    def finish_trace(self, trace_id: int, state: TraceState, finished_at: datetime) -> None:
        with Session(self.engine) as db:
            rec = db.get(TraceRecord, trace_id)
            if rec is None:
                raise KeyError(trace_id)
            rec.status = state.status
            rec.error = state.error
            rec.finished_at = finished_at
            db.add(rec)
            for old in db.exec(select(HopRecord).where(HopRecord.trace_id == trace_id)):
                db.delete(old)
            db.add_all(_hop_record(trace_id, hop) for hop in state.hops)
            db.commit()

    def add_monitor_samples(self, rows: list[MonitorSampleRecord]) -> None:
        with Session(self.engine) as db:
            db.add_all(rows)
            db.commit()

    def list_traces(self, target: str | None = None, limit: int = 20) -> list[TraceRecord]:
        query = select(TraceRecord).order_by(TraceRecord.id.desc()).limit(limit)
        if target:
            query = query.where(TraceRecord.target == target)
        with Session(self.engine) as db:
            return list(db.exec(query))

    def get_trace(self, trace_id: int) -> tuple[TraceRecord, list[HopRecord]] | None:
        with Session(self.engine) as db:
            rec = db.get(TraceRecord, trace_id)
            if rec is None:
                return None
            hops = db.exec(
                select(HopRecord).where(HopRecord.trace_id == trace_id).order_by(HopRecord.hop_index)
            )
            return rec, list(hops)

    def monitor_samples(self, trace_id: int) -> list[MonitorSampleRecord]:
        query = (
            select(MonitorSampleRecord)
            .where(MonitorSampleRecord.trace_id == trace_id)
            .order_by(MonitorSampleRecord.ts, MonitorSampleRecord.hop_index)
        )
        with Session(self.engine) as db:
            return list(db.exec(query))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/core/test_store.py -v`
Expected: all passed. If `test_trace_roundtrip` fails with `DetachedInstanceError`, add `expire_on_commit=False` to each `Session(...)` call.

- [ ] **Step 6: Commit**

```bash
git add src/traceviz/core/store tests/core/test_store.py
git commit -m "feat: SQLite store for traces, hops and monitor samples"
```

---

### Task 8: SessionManager

**Files:**
- Create: `src/traceviz/core/sessions/manager.py`
- Modify: `tests/fakes.py` (append `FakeEngine`)
- Test: `tests/core/test_manager.py`

**Interfaces:**
- Consumes: `ProbeEngine`, `ProbeError`, `ProbeProtocol` (Task 3); `ResolvedTarget` (Task 2); `TraceState` (Task 4); `GeoLookup` (Task 5); `TraceRepository`, `MonitorSampleRecord` (Task 7).
- Produces:
  - `class TooManySessions(RuntimeError)`, `class SessionNotFound(KeyError)`.
  - `SessionManager(engine: ProbeEngine, geo: GeoLookup, repo: TraceRepository, *, max_sessions=3, trace_timeout_s=300.0, sample_interval_s=10.0, clock=lambda: datetime.now(UTC))` with:
    - `async start(target: ResolvedTarget, *, kind: SessionKind = "trace", protocol: ProbeProtocol = "icmp", max_hops: int = 30, cycles: int = 10) -> int` (returns trace id; `monitor` ignores `cycles` and runs unlimited)
    - `subscribe(session_id: int) -> AsyncIterator[TraceState]` — yields the current snapshot immediately, then the latest snapshot after each change (slow consumers skip intermediate ones), ends after the final non-`running` snapshot. When the last subscriber leaves a still-running session, the session is stopped.
    - `async stop(session_id: int) -> None`, `async wait(session_id: int) -> TraceState`, `async close() -> None` (stops all).
  - `tests/fakes.py`: `FakeEngine(events, *, delay=0.0, error=None, hang=False, check_error=None)` with `.calls` and `.running`.

- [ ] **Step 1: Append fake engine** to `tests/fakes.py` (add `import asyncio` at the top)

```python
class FakeEngine:
    """Scripted ProbeEngine for tests."""

    def __init__(self, events, *, delay=0.0, error=None, hang=False, check_error=None):
        self.events = list(events)
        self.delay = delay
        self.error = error
        self.hang = hang
        self.check_error = check_error
        self.calls: list[tuple] = []
        self.running = 0

    async def run(self, ip, protocol="icmp", max_hops=30, cycles=10):
        self.calls.append((ip, protocol, max_hops, cycles))
        self.running += 1
        try:
            for event in self.events:
                if self.delay:
                    await asyncio.sleep(self.delay)
                yield event
            if self.error:
                raise self.error
            if self.hang:
                await asyncio.Event().wait()
        finally:
            self.running -= 1

    async def self_check(self):
        if self.check_error:
            raise self.check_error
```

- [ ] **Step 2: Write the failing test** — `tests/core/test_manager.py`

```python
import asyncio

import pytest

from tests.fakes import CITY_FIXTURE, DictReader, FakeEngine, fixture_events
from traceviz.core.geo.lookup import GeoLookup
from traceviz.core.probe.engine import ProbeError
from traceviz.core.probe.target import ResolvedTarget
from traceviz.core.sessions.manager import SessionManager, SessionNotFound, TooManySessions
from traceviz.core.store.repo import TraceRepository, init_db

TARGET = ResolvedTarget("one.one.one.one", "1.1.1.1")


@pytest.fixture
def repo(tmp_path):
    return TraceRepository(init_db(tmp_path / "t.db"))


def make(repo, engine, **kw):
    geo = GeoLookup(city=DictReader(CITY_FIXTURE), asn=None)
    return SessionManager(engine, geo, repo, **kw)


async def test_trace_completes_enriches_and_persists(repo):
    engine = FakeEngine(fixture_events())
    mgr = make(repo, engine)
    sid = await mgr.start(TARGET, protocol="udp", max_hops=20, cycles=3)
    final = await mgr.wait(sid)
    assert engine.calls == [("1.1.1.1", "udp", 20, 3)]
    assert final.status == "completed"
    assert len(final.hops) == 9
    assert final.hops[0].geo.status == "local"
    assert final.hops[8].geo.city == "Sydney"
    rec, hops = repo.get_trace(sid)
    assert rec.status == "completed" and rec.target == "one.one.one.one" and len(hops) == 9


async def test_subscribe_yields_snapshots_until_final(repo):
    mgr = make(repo, FakeEngine(fixture_events(), delay=0.001))
    sid = await mgr.start(TARGET)
    states = [s async for s in mgr.subscribe(sid)]
    assert states[0].status == "running"
    assert states[-1].status == "completed"
    assert len(states[-1].hops) == 9


async def test_subscribe_after_finish_yields_final_once(repo):
    mgr = make(repo, FakeEngine(fixture_events()))
    sid = await mgr.start(TARGET)
    await mgr.wait(sid)
    states = [s async for s in mgr.subscribe(sid)]
    assert [s.status for s in states] == ["completed"]


async def test_probe_error_marks_failed_and_keeps_partial_hops(repo):
    engine = FakeEngine(fixture_events()[:20], error=ProbeError("mtr exploded"))
    mgr = make(repo, engine)
    sid = await mgr.start(TARGET)
    final = await mgr.wait(sid)
    assert final.status == "failed" and final.error == "mtr exploded"
    rec, hops = repo.get_trace(sid)
    assert rec.status == "failed" and rec.error == "mtr exploded" and len(hops) > 0


async def test_trace_timeout(repo):
    engine = FakeEngine(fixture_events()[:5], hang=True)
    mgr = make(repo, engine, trace_timeout_s=0.05)
    final = await mgr.wait(await mgr.start(TARGET))
    assert final.status == "failed" and "timed out" in final.error
    assert engine.running == 0


async def test_stop_kills_probe_and_saves_stopped(repo):
    engine = FakeEngine(fixture_events()[:5], hang=True)
    mgr = make(repo, engine)
    sid = await mgr.start(TARGET)
    await asyncio.sleep(0.01)
    await mgr.stop(sid)
    assert engine.running == 0
    assert (await mgr.wait(sid)).status == "stopped"
    assert repo.get_trace(sid)[0].status == "stopped"


async def test_last_subscriber_leaving_stops_session(repo):
    engine = FakeEngine(fixture_events()[:5], hang=True)
    mgr = make(repo, engine)
    sid = await mgr.start(TARGET, kind="monitor")
    gen = mgr.subscribe(sid)
    await anext(gen)
    await gen.aclose()
    assert (await mgr.wait(sid)).status == "stopped"
    assert engine.running == 0


async def test_session_limit(repo):
    mgr = make(repo, FakeEngine([], hang=True), max_sessions=1)
    await mgr.start(TARGET)
    with pytest.raises(TooManySessions):
        await mgr.start(TARGET)
    await mgr.close()


async def test_finished_sessions_free_their_slot(repo):
    mgr = make(repo, FakeEngine(fixture_events()), max_sessions=1)
    await mgr.wait(await mgr.start(TARGET))
    await mgr.wait(await mgr.start(TARGET))


async def test_unknown_session(repo):
    mgr = make(repo, FakeEngine([]))
    with pytest.raises(SessionNotFound):
        await mgr.stop(42)


async def test_monitor_runs_unlimited_and_samples_add_up(repo):
    events = fixture_events() * 4
    engine = FakeEngine(events, delay=0.001)
    mgr = make(repo, engine, sample_interval_s=0.02)
    sid = await mgr.start(TARGET, kind="monitor", cycles=3)
    final = await mgr.wait(sid)
    assert engine.calls[0][3] is None
    samples = repo.monitor_samples(sid)
    assert len({s.ts for s in samples}) >= 2
    for hop in final.hops:
        hop_samples = [s for s in samples if s.hop_index == hop.index]
        assert sum(s.sent for s in hop_samples) == hop.sent
        assert sum(s.received for s in hop_samples) == hop.received
```

Also append to `tests/fakes.py`:
```python
CITY_FIXTURE = {
    "1.1.1.1": {
        "city": {"names": {"en": "Sydney"}},
        "country": {"iso_code": "AU", "names": {"en": "Australia"}},
        "location": {"latitude": -33.8688, "longitude": 151.209},
    },
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/core/test_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'traceviz.core.sessions.manager'`

- [ ] **Step 4: Implement** — `src/traceviz/core/sessions/manager.py`

```python
import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import UTC, datetime

from traceviz.core.geo.lookup import GeoLookup
from traceviz.core.probe.engine import ProbeEngine, ProbeError, ProbeProtocol
from traceviz.core.probe.target import ResolvedTarget
from traceviz.core.sessions.state import SessionKind, TraceState
from traceviz.core.store.models import MonitorSampleRecord
from traceviz.core.store.repo import TraceRepository


class TooManySessions(RuntimeError):
    """The concurrent session limit has been reached."""


class SessionNotFound(KeyError):
    """No session with that id exists in this manager."""


@dataclass
class _Session:
    id: int
    state: TraceState
    task: asyncio.Task | None = None
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    # hop index -> (sent, received, sum_ms) at the last monitor flush
    flushed: dict[int, tuple[int, int, float]] = field(default_factory=dict)


class SessionManager:
    def __init__(
        self,
        engine: ProbeEngine,
        geo: GeoLookup,
        repo: TraceRepository,
        *,
        max_sessions: int = 3,
        trace_timeout_s: float = 300.0,
        sample_interval_s: float = 10.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.engine = engine
        self.geo = geo
        self.repo = repo
        self.max_sessions = max_sessions
        self.trace_timeout_s = trace_timeout_s
        self.sample_interval_s = sample_interval_s
        self.clock = clock
        self._sessions: dict[int, _Session] = {}

    def _get(self, session_id: int) -> _Session:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise SessionNotFound(session_id) from None

    async def start(
        self,
        target: ResolvedTarget,
        *,
        kind: SessionKind = "trace",
        protocol: ProbeProtocol = "icmp",
        max_hops: int = 30,
        cycles: int = 10,
    ) -> int:
        active = sum(1 for s in self._sessions.values() if not s.done.is_set())
        if active >= self.max_sessions:
            raise TooManySessions(f"at most {self.max_sessions} sessions can run at once")
        state = TraceState(target=target.target, target_ip=target.ip, protocol=protocol, kind=kind)
        session = _Session(self.repo.create_trace(state, self.clock()), state)
        self._sessions[session.id] = session
        session.task = asyncio.create_task(
            self._run(session, max_hops, None if kind == "monitor" else cycles)
        )
        return session.id

    async def _run(self, s: _Session, max_hops: int, cycles: int | None) -> None:
        state = s.state
        timeout = self.trace_timeout_s if state.kind == "trace" else None
        sampler = asyncio.create_task(self._sample_loop(s)) if state.kind == "monitor" else None
        try:
            async with asyncio.timeout(timeout):
                events = self.engine.run(state.target_ip, state.protocol, max_hops, cycles)
                async with aclosing(events):
                    async for event in events:
                        hop = state.apply(event)
                        if hop.ip and hop.geo is None:
                            hop.geo = self.geo.lookup(hop.ip)
                        self._publish(s)
            state.status = "completed"
        except asyncio.CancelledError:
            state.status = "stopped"
        except TimeoutError:
            state.status = "failed"
            state.error = f"timed out after {timeout:.0f}s"
        except ProbeError as e:
            state.status = "failed"
            state.error = str(e)
        finally:
            if sampler:
                sampler.cancel()
                await asyncio.gather(sampler, return_exceptions=True)
                self._flush_samples(s)
            self.repo.finish_trace(s.id, state, self.clock())
            s.done.set()
            self._publish(s)

    async def _sample_loop(self, s: _Session) -> None:
        while True:
            await asyncio.sleep(self.sample_interval_s)
            self._flush_samples(s)

    def _flush_samples(self, s: _Session) -> None:
        now = self.clock()
        rows = []
        for hop in s.state.hops:
            prev_sent, prev_received, prev_sum = s.flushed.get(hop.index, (0, 0, 0.0))
            d_sent = hop.sent - prev_sent
            if d_sent <= 0:
                continue
            d_received = hop.received - prev_received
            avg = (hop.sum_ms - prev_sum) / d_received if d_received else None
            rows.append(
                MonitorSampleRecord(
                    trace_id=s.id, ts=now, hop_index=hop.index,
                    sent=d_sent, received=d_received, avg_ms=avg,
                )
            )
            s.flushed[hop.index] = (hop.sent, hop.received, hop.sum_ms)
        if rows:
            self.repo.add_monitor_samples(rows)

    def _publish(self, s: _Session) -> None:
        snap = s.state.snapshot()
        for queue in s.subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(snap)

    async def subscribe(self, session_id: int) -> AsyncIterator[TraceState]:
        s = self._get(session_id)
        queue: asyncio.Queue[TraceState] = asyncio.Queue(maxsize=1)
        queue.put_nowait(s.state.snapshot())
        s.subscribers.add(queue)
        try:
            while True:
                snap = await queue.get()
                yield snap
                if snap.status != "running":
                    return
        finally:
            s.subscribers.discard(queue)
            if not s.subscribers and not s.done.is_set():
                await self.stop(session_id)

    async def stop(self, session_id: int) -> None:
        s = self._get(session_id)
        if s.task and not s.task.done():
            s.task.cancel()
            await asyncio.gather(s.task, return_exceptions=True)

    async def wait(self, session_id: int) -> TraceState:
        s = self._get(session_id)
        await s.done.wait()
        return s.state.snapshot()

    async def close(self) -> None:
        for session_id in list(self._sessions):
            await self.stop(session_id)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/core -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/traceviz/core/sessions/manager.py tests/fakes.py tests/core/test_manager.py
git commit -m "feat: SessionManager orchestrates probes, geo, storage and pub/sub"
```

---

### Task 9: Config, rendering and `trace` / `monitor` commands

**Files:**
- Create: `src/traceviz/config.py`, `src/traceviz/cli/__init__.py` (empty), `src/traceviz/cli/render.py`, `src/traceviz/cli/app.py`, `src/traceviz/__main__.py`, `tests/cli/__init__.py` (empty)
- Test: `tests/cli/test_render.py`, `tests/cli/test_app.py`

**Interfaces:**
- Consumes: everything from Tasks 2–8.
- Produces:
  - `Settings(data_dir: Path, geo_dir: Path)` with `.db_path` and `Settings.from_env()`.
  - `render_trace(state: TraceState) -> rich.table.Table`; `format_location(geo: GeoResult | None) -> str`.
  - Typer `app` in `traceviz.cli.app` with commands `trace`, `monitor`; module-level `make_engine() -> ProbeEngine` and the imported name `resolve_target` (both monkeypatched by tests).

- [ ] **Step 1: Write the failing tests**

`tests/cli/test_render.py`:
```python
from rich.console import Console

from tests.fakes import fixture_events
from traceviz.cli.render import format_location, render_trace
from traceviz.core.geo.lookup import GeoResult
from traceviz.core.sessions.state import TraceState


def rendered(state) -> str:
    console = Console(record=True, width=200)
    console.print(render_trace(state))
    return console.export_text()


def test_format_location():
    assert format_location(None) == ""
    assert format_location(GeoResult("local")) == "local"
    assert format_location(GeoResult("unknown")) == "unknown location"
    assert format_location(GeoResult("geo", 1, 2, "London", "GB")) == "London, GB"
    assert format_location(GeoResult("geo", 1, 2, None, "AU", approximate=True)) == "AU ~approx"


def test_render_shows_hops_silent_rows_and_status():
    state = TraceState("1.1.1.1", "1.1.1.1", "icmp", "trace")
    for e in fixture_events():
        state.apply(e)
    state.hops_by_index[8].geo = GeoResult("geo", 1, 2, "Sydney", "AU", asn=13335, approximate=True)
    text = rendered(state)
    assert "trace to 1.1.1.1 (1.1.1.1) · ICMP · running" in text
    assert "_gateway (10.100.0.1)" in text
    assert "no reply" in text
    assert "Sydney, AU ~approx" in text
    assert "AS13335" in text
    assert "1314.0" in text  # hop 1 average
```

`tests/cli/test_app.py`:
```python
import json

import pytest
from typer.testing import CliRunner

from tests.fakes import FakeEngine, fixture_events
from traceviz.cli import app as cli
from traceviz.core.probe.engine import ProbeError
from traceviz.core.probe.events import HopEvent
from traceviz.core.probe.target import InvalidTarget, ResolvedTarget
from traceviz.core.store.repo import TraceRepository, init_db

runner = CliRunner()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "resolve_target", lambda t: ResolvedTarget(t, "1.1.1.1"))
    return {"TRACEVIZ_DATA_DIR": str(tmp_path), "TRACEVIZ_GEO_DIR": str(tmp_path / "nogeo"),
            "COLUMNS": "200"}


def use_engine(monkeypatch, engine):
    monkeypatch.setattr(cli, "make_engine", lambda: engine)
    return engine


def test_trace_prints_table_and_persists(env, monkeypatch, tmp_path):
    use_engine(monkeypatch, FakeEngine(fixture_events()))
    result = runner.invoke(cli.app, ["trace", "one.one.one.one"], env=env)
    assert result.exit_code == 0, result.output
    assert "10.100.0.1" in result.output
    assert "completed" in result.output
    assert "traceviz fetch-geo" in result.output  # missing geo DB warning
    traces = TraceRepository(init_db(tmp_path / "traceviz.db")).list_traces()
    assert [t.status for t in traces] == ["completed"]


def test_trace_json_output(env, monkeypatch):
    engine = use_engine(monkeypatch, FakeEngine(fixture_events()))
    result = runner.invoke(
        cli.app, ["trace", "one.one.one.one", "--json", "-p", "tcp", "--max-hops", "20", "--cycles", "3"], env=env
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert engine.calls == [("1.1.1.1", "tcp", 20, 3)]
    assert data["id"] == 1 and data["status"] == "completed" and data["destination_reached"] is True
    assert [h["hop"] for h in data["hops"]] == list(range(1, 10))
    assert set(data["hops"][0]) == {"hop", "ip", "hostname", "sent", "received", "loss_pct", "last_ms",
                                    "avg_ms", "best_ms", "worst_ms", "jitter_ms", "geo"}
    assert data["hops"][0]["geo"] == {"status": "local", "lat": None, "lon": None, "city": None,
                                      "country": None, "country_name": None, "asn": None, "org": None,
                                      "approximate": False}


def test_invalid_target_exits_2_without_probing(env, monkeypatch):
    engine = use_engine(monkeypatch, FakeEngine([]))

    def reject(t):
        raise InvalidTarget(f"not a valid hostname or IP address: {t!r}")

    monkeypatch.setattr(cli, "resolve_target", reject)
    result = runner.invoke(cli.app, ["trace", "--", "--help"], env=env)
    assert result.exit_code == 2
    assert "not a valid hostname" in result.output
    assert engine.calls == []


def test_probe_failure_exits_1_with_hint(env, monkeypatch):
    use_engine(monkeypatch, FakeEngine([], error=ProbeError("mtr could not open raw sockets ... NET_RAW")))
    result = runner.invoke(cli.app, ["trace", "1.1.1.1"], env=env)
    assert result.exit_code == 1
    assert "NET_RAW" in result.output


def test_blocked_icmp_suggests_tcp(env, monkeypatch):
    events = [HopEvent("sent", 0), HopEvent("host", 0, ip="10.0.0.1"), HopEvent("reply", 0, rtt_ms=1.0),
              HopEvent("sent", 1), HopEvent("sent", 2)]
    use_engine(monkeypatch, FakeEngine(events))
    result = runner.invoke(cli.app, ["trace", "1.1.1.1"], env=env)
    assert result.exit_code == 0
    assert "--protocol tcp" in result.output


def test_monitor_runs_until_engine_ends(env, monkeypatch):
    engine = use_engine(monkeypatch, FakeEngine(fixture_events()))
    result = runner.invoke(cli.app, ["monitor", "1.1.1.1"], env=env)
    assert result.exit_code == 0, result.output
    assert engine.calls[0][3] is None
    assert "monitor to 1.1.1.1" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/cli -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'traceviz.cli'`

- [ ] **Step 3: Implement config** — `src/traceviz/config.py`

```python
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    geo_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "traceviz.db"

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("TRACEVIZ_DATA_DIR") or Path.home() / ".local/share/traceviz")
        geo_dir = Path(os.environ.get("TRACEVIZ_GEO_DIR") or data_dir / "geo")
        return cls(data_dir=data_dir, geo_dir=geo_dir)
```

- [ ] **Step 4: Implement rendering** — `src/traceviz/cli/render.py`

```python
from rich.table import Table

from traceviz.core.geo.lookup import GeoResult
from traceviz.core.sessions.state import HopStats, TraceState

_STATUS_STYLE = {"running": "cyan", "completed": "green", "failed": "red", "stopped": "yellow"}


def _ms(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}"


def format_location(geo: GeoResult | None) -> str:
    if geo is None:
        return ""
    if geo.status == "local":
        return "local"
    if geo.status == "unknown":
        return "unknown location"
    place = ", ".join(p for p in (geo.city, geo.country) if p)
    return f"{place} ~approx" if geo.approximate else place


def _host(hop: HopStats) -> str:
    if hop.ip is None:
        return "[dim]no reply[/dim]"
    if hop.hostname and hop.hostname != hop.ip:
        return f"{hop.hostname} ({hop.ip})"
    return hop.ip


def _loss(hop: HopStats) -> str:
    style = "green" if hop.loss_pct == 0 else "yellow" if hop.loss_pct < 20 else "red"
    return f"[{style}]{hop.loss_pct:.0f}%[/{style}]"


def render_trace(state: TraceState) -> Table:
    style = _STATUS_STYLE[state.status]
    table = Table(
        title=f"{state.kind} to {state.target} ({state.target_ip}) · {state.protocol.upper()} · "
        f"[{style}]{state.status}[/{style}]",
        title_justify="left",
    )
    for name in ("#", "Host", "Location", "ASN", "Loss", "Sent", "Last", "Avg", "Best", "Worst", "Jitter"):
        table.add_column(name, justify="right" if name not in ("Host", "Location", "ASN") else "left")
    for hop in state.hops:
        asn = f"AS{hop.geo.asn}" if hop.geo and hop.geo.asn else ""
        table.add_row(
            str(hop.index + 1), _host(hop), format_location(hop.geo), asn, _loss(hop), str(hop.sent),
            _ms(hop.last_ms), _ms(hop.avg_ms), _ms(hop.best_ms), _ms(hop.worst_ms), _ms(hop.jitter_ms),
        )
    return table
```

- [ ] **Step 5: Implement commands** — `src/traceviz/cli/app.py`

```python
"""traceviz command-line interface."""

import asyncio
import json
from enum import Enum
from typing import Annotated

import typer
from rich.console import Console
from rich.live import Live
from rich.markup import escape

from traceviz.cli.render import render_trace
from traceviz.config import Settings
from traceviz.core.geo.lookup import GeoLookup
from traceviz.core.probe.engine import MtrEngine, ProbeEngine
from traceviz.core.probe.target import InvalidTarget, resolve_target
from traceviz.core.sessions.manager import SessionManager
from traceviz.core.sessions.state import SessionKind, TraceState
from traceviz.core.store.repo import TraceRepository, init_db

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Visual traceroute and route monitor.")


def out() -> Console:
    # Built per call so COLUMNS/terminal detection reflect the current environment.
    return Console()


def err() -> Console:
    return Console(stderr=True)


class Proto(str, Enum):
    icmp = "icmp"
    udp = "udp"
    tcp = "tcp"


ProtoOpt = Annotated[Proto, typer.Option("--protocol", "-p", help="Probe protocol (tcp uses port 443).")]
MaxHopsOpt = Annotated[int, typer.Option("--max-hops", min=1, max=64, help="Maximum TTL.")]


def make_engine() -> ProbeEngine:
    return MtrEngine()


@app.command()
def trace(
    target: str,
    protocol: ProtoOpt = Proto.icmp,
    max_hops: MaxHopsOpt = 30,
    cycles: Annotated[int, typer.Option(min=1, max=100, help="Probes per hop.")] = 10,
    json_out: Annotated[bool, typer.Option("--json", help="Print the final result as JSON.")] = False,
) -> None:
    """Trace the route to TARGET once."""
    raise typer.Exit(asyncio.run(_run(target, "trace", protocol.value, max_hops, cycles, json_out)))


@app.command()
def monitor(target: str, protocol: ProtoOpt = Proto.icmp, max_hops: MaxHopsOpt = 30) -> None:
    """Continuously probe the route to TARGET (MTR-style). Press Ctrl-C to stop."""
    try:
        code = asyncio.run(_run(target, "monitor", protocol.value, max_hops, 10, False))
    except KeyboardInterrupt:
        err().print("Monitor stopped; results saved.")
        code = 0
    raise typer.Exit(code)


async def _run(
    target: str, kind: SessionKind, protocol: str, max_hops: int, cycles: int, json_out: bool
) -> int:
    try:
        resolved = resolve_target(target)
    except InvalidTarget as e:
        err().print(f"[red]Error:[/red] {escape(str(e))}")
        return 2
    settings = Settings.from_env()
    geo = GeoLookup.open(settings.geo_dir)
    if not geo.available and not json_out:
        err().print("[yellow]No geolocation database — run `traceviz fetch-geo` to see hop locations.[/yellow]")
    manager = SessionManager(make_engine(), geo, TraceRepository(init_db(settings.db_path)))
    try:
        sid = await manager.start(resolved, kind=kind, protocol=protocol, max_hops=max_hops, cycles=cycles)
        final = await _follow(manager, sid, json_out)
    finally:
        await manager.close()
    if json_out:
        print(json.dumps({"id": sid, **final.to_dict()}))
    if final.status == "failed":
        err().print(f"[red]Probe failed:[/red] {escape(final.error or 'unknown error')}")
        return 1
    if final.suggest_other_protocol:
        err().print("[yellow]No hops answered beyond the first. ICMP may be filtered — try --protocol tcp.[/yellow]")
    return 0


async def _follow(manager: SessionManager, sid: int, json_out: bool) -> TraceState:
    final: TraceState | None = None
    if json_out:
        async for state in manager.subscribe(sid):
            final = state
    else:
        with Live(console=out(), refresh_per_second=8) as live:
            async for state in manager.subscribe(sid):
                live.update(render_trace(state))
                final = state
    assert final is not None
    return final
```

`src/traceviz/__main__.py`:
```python
from traceviz.cli.app import app

app()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/cli -v`
Expected: all passed. If `test_trace_prints_table_and_persists` cannot find the table in `result.output`, it is because Rich `Live` renders the final frame on exit only when the console is not a terminal — confirm the assertion text appears once at the end; do not add `force_terminal`.

- [ ] **Step 7: Manual check against real mtr**

Run: `uv run traceviz trace 1.1.1.1 --cycles 3`
Expected: a live-updating table ending at `one.one.one.one (1.1.1.1)` with status `completed` and the yellow "run `traceviz fetch-geo`" warning. If it fails with a raw-socket error, the message must include the `setcap` hint.

- [ ] **Step 8: Commit**

```bash
git add src/traceviz/config.py src/traceviz/cli src/traceviz/__main__.py tests/cli
git commit -m "feat: trace and monitor CLI commands with live Rich table"
```

---

### Task 10: `history`, `doctor`, `fetch-geo` commands, real-mtr test, README

**Files:**
- Modify: `src/traceviz/cli/app.py` (append commands)
- Create: `tests/integration/__init__.py` (empty), `tests/integration/test_real_mtr.py`, `README.md`
- Test: `tests/cli/test_app.py` (append)

**Interfaces:**
- Consumes: `TraceRepository.list_traces`, `MtrEngine.self_check`, `download_latest`, `ATTRIBUTION`, `GeoLookup.open`.
- Produces: commands `traceviz history [--target T] [--limit N] [--json]`, `traceviz doctor` (exit 1 if mtr unusable), `traceviz fetch-geo`.

- [ ] **Step 1: Append failing tests** to `tests/cli/test_app.py`

```python
def test_history_lists_newest_first(env, monkeypatch):
    use_engine(monkeypatch, FakeEngine(fixture_events()))
    runner.invoke(cli.app, ["trace", "a.example"], env=env)
    runner.invoke(cli.app, ["trace", "b.example"], env=env)
    result = runner.invoke(cli.app, ["history", "--json"], env=env)
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert [r["target"] for r in rows] == ["b.example", "a.example"]
    assert rows[0]["status"] == "completed"
    filtered = json.loads(runner.invoke(cli.app, ["history", "--json", "--target", "a.example"], env=env).stdout)
    assert [r["target"] for r in filtered] == ["a.example"]


def test_history_table(env, monkeypatch):
    use_engine(monkeypatch, FakeEngine(fixture_events()))
    runner.invoke(cli.app, ["trace", "a.example"], env=env)
    result = runner.invoke(cli.app, ["history"], env=env)
    assert result.exit_code == 0 and "a.example" in result.output


def test_doctor_reports_ok(env, monkeypatch):
    use_engine(monkeypatch, FakeEngine([]))
    result = runner.invoke(cli.app, ["doctor"], env=env)
    assert result.exit_code == 0
    assert "mtr: ok" in result.output
    assert "geolocation: missing" in result.output


def test_doctor_reports_mtr_problem(env, monkeypatch):
    use_engine(monkeypatch, FakeEngine([], check_error=ProbeError("raw sockets ... NET_RAW")))
    result = runner.invoke(cli.app, ["doctor"], env=env)
    assert result.exit_code == 1
    assert "NET_RAW" in result.output


def test_fetch_geo(env, monkeypatch, tmp_path):
    calls = []

    def fake_download(dest, client, today):
        calls.append(dest)
        return "2026-10"

    monkeypatch.setattr(cli, "download_latest", fake_download)
    result = runner.invoke(cli.app, ["fetch-geo"], env=env)
    assert result.exit_code == 0
    assert calls == [tmp_path / "nogeo"]
    assert "2026-10" in result.output and "DB-IP" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/cli/test_app.py -v`
Expected: the five new tests FAIL with `No such command 'history'` / `'doctor'` / `'fetch-geo'`.

- [ ] **Step 3: Implement** — append to `src/traceviz/cli/app.py` (add imports at the top: `from datetime import date`, `import httpx`, `from rich.table import Table`, `from traceviz.core.geo.download import ATTRIBUTION, download_latest`, and change the engine import to `from traceviz.core.probe.engine import MtrEngine, ProbeEngine, ProbeError`)

```python
@app.command()
def history(
    target: Annotated[str | None, typer.Option("--target", help="Only traces to this target.")] = None,
    limit: Annotated[int, typer.Option(min=1, max=500)] = 20,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List recent traces and monitors."""
    repo = TraceRepository(init_db(Settings.from_env().db_path))
    rows = repo.list_traces(target=target, limit=limit)
    if json_out:
        print(json.dumps([r.model_dump(mode="json") for r in rows]))
        return
    table = Table(title="History", title_justify="left")
    for name in ("ID", "Started", "Kind", "Target", "Protocol", "Status"):
        table.add_column(name)
    for r in rows:
        table.add_row(str(r.id), r.started_at.strftime("%Y-%m-%d %H:%M"), r.kind, r.target,
                      r.protocol.upper(), r.status)
    out().print(table)


@app.command()
def doctor() -> None:
    """Check that probing, geolocation and storage are ready."""
    settings = Settings.from_env()
    ok = True
    try:
        asyncio.run(make_engine().self_check())
        out().print("[green]mtr: ok[/green]")
    except ProbeError as e:
        ok = False
        out().print(f"[red]mtr: failed[/red] — {escape(str(e))}")
    if GeoLookup.open(settings.geo_dir).available:
        out().print(f"[green]geolocation: ok[/green] ({settings.geo_dir})")
    else:
        out().print("[yellow]geolocation: missing[/yellow] — run `traceviz fetch-geo`")
    out().print(f"database: {settings.db_path}")
    raise typer.Exit(0 if ok else 1)


@app.command("fetch-geo")
def fetch_geo() -> None:
    """Download the free DB-IP Lite city and ASN databases."""
    settings = Settings.from_env()
    with httpx.Client(timeout=120) as client:
        month = download_latest(settings.geo_dir, client, date.today())
    out().print(f"Downloaded DB-IP Lite {month} to {settings.geo_dir}")
    out().print(ATTRIBUTION)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all passed (slow tests deselected)

- [ ] **Step 5: Write the real-mtr test** — `tests/integration/test_real_mtr.py`

```python
import json
import os
import subprocess
import sys

import pytest


@pytest.mark.slow
def test_real_trace_to_cloudflare(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "traceviz", "trace", "1.1.1.1", "--cycles", "2", "--json"],
        env={**os.environ, "TRACEVIZ_DATA_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "completed"
    assert data["destination_reached"] is True
    assert data["hops"][-1]["ip"] == "1.1.1.1"
```

Run: `uv run pytest -m slow -v`
Expected: 1 passed (needs network and working mtr).

- [ ] **Step 6: Write README.md**

````markdown
# traceviz

Visual traceroute, MTR-style route monitor and (soon) speed test — in your terminal and browser.

## Quick start (local)

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/) and `mtr` (`sudo apt install mtr-tiny`).

```bash
uv sync
uv run traceviz doctor          # checks mtr permissions, geo DB, database path
uv run traceviz fetch-geo       # downloads free DB-IP Lite databases (~130 MB)
uv run traceviz trace google.com
uv run traceviz monitor 1.1.1.1 # Ctrl-C to stop
uv run traceviz history
```

Options: `--protocol icmp|udp|tcp`, `--max-hops N`, `--cycles N` (trace), `--json` (trace, history).

Data lives in `~/.local/share/traceviz` (override with `TRACEVIZ_DATA_DIR`; geo DB dir with `TRACEVIZ_GEO_DIR`).

## Development

```bash
uv run pytest            # unit tests
uv run pytest -m slow    # real mtr against 1.1.1.1
```

## Attribution

IP geolocation by DB-IP (https://db-ip.com), licensed CC BY 4.0.
````

- [ ] **Step 7: Manual check**

Run: `uv run traceviz fetch-geo && uv run traceviz trace 1.1.1.1 --cycles 3`
Expected: download succeeds; trace table now shows locations (private hops as `local`, Cloudflare as `… ~approx`) and ASNs.

- [ ] **Step 8: Commit**

```bash
git add src/traceviz/cli/app.py tests/cli/test_app.py tests/integration README.md
git commit -m "feat: history, doctor and fetch-geo commands; README"
```
