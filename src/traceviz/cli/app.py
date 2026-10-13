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
