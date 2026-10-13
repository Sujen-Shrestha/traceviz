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

## Web UI

Requires Node 20+; the UI uses pnpm (run through `npx`, nothing to install globally).

```bash
npx -y pnpm@10.34.6 --dir frontend install
npx -y pnpm@10.34.6 --dir frontend build
uv run traceviz serve           # http://127.0.0.1:8080
```

Enter a host, pick Trace or Monitor, and watch hops appear on the map. Closing the tab stops a running probe.
`serve` listens on 127.0.0.1 only; `--host 0.0.0.0` exposes it to your network (it warns you).

Frontend development with hot reload: run `uv run traceviz serve` and, in another terminal,
`npx -y pnpm@10.34.6 --dir frontend dev` (Vite proxies `/api` and `/ws` to port 8080).

Map data: Natural Earth (public domain) via world-atlas.

## Development

```bash
uv run pytest            # unit tests
uv run pytest -m slow    # real mtr against 1.1.1.1
```

## Attribution

IP geolocation by DB-IP (https://db-ip.com), licensed CC BY 4.0.
