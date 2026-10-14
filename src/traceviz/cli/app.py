"""traceviz command-line interface."""

import asyncio
import json
import os
import shlex
import signal
from datetime import date
from enum import Enum
from typing import Annotated

import httpx
import typer
import uvicorn
from rich.console import Console
from rich.live import Live
from rich.markup import escape
from rich.table import Table

from traceviz.cli.render import render_trace_with_summary
from traceviz.config import Settings
from traceviz.core.geo.download import ATTRIBUTION, download_latest
from traceviz.core.geo.lookup import GeoLookup
from traceviz.core.probe.engine import MtrEngine, ProbeEngine, ProbeError
from traceviz.core.probe.target import InvalidTarget, resolve_target
from traceviz.core.sessions.manager import SessionManager
from traceviz.core.sessions.state import SessionKind, TraceState
from traceviz.core.sessions.summary import summarize
from traceviz.core.store.repo import TraceRepository, init_db
from traceviz.web.app import LOCAL_HOSTS, create_app

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
    # TRACEVIZ_MTR replaces the mtr command (tests use it to substitute a fake mtr).
    command = os.environ.get("TRACEVIZ_MTR")
    return MtrEngine(command=shlex.split(command)) if command else MtrEngine()


@app.command()
def trace(
    target: str,
    protocol: ProtoOpt = Proto.icmp,
    max_hops: MaxHopsOpt = 30,
    cycles: Annotated[int, typer.Option(min=1, max=100, help="Probes per hop.")] = 10,
    json_out: Annotated[bool, typer.Option("--json", help="Print the final result as JSON.")] = False,
) -> None:
    """Trace the route to TARGET once."""
    try:
        code = asyncio.run(_run(target, "trace", protocol.value, max_hops, cycles, json_out))
    except (KeyboardInterrupt, asyncio.CancelledError):
        err().print("Trace stopped; partial results saved.")
        code = _interrupted_exit_code()
    raise typer.Exit(code)


@app.command()
def monitor(target: str, protocol: ProtoOpt = Proto.icmp, max_hops: MaxHopsOpt = 30) -> None:
    """Continuously probe the route to TARGET (MTR-style). Press Ctrl-C to stop."""
    try:
        code = asyncio.run(_run(target, "monitor", protocol.value, max_hops, 10, False))
    except (KeyboardInterrupt, asyncio.CancelledError):
        err().print("Monitor stopped; results saved.")
        code = 0
    raise typer.Exit(code)


_termination: list[int] = []  # signal that stopped the current run, if any


def _stop_on_termination() -> None:
    """Treat SIGTERM (docker stop) and SIGHUP (closed terminal) like Ctrl-C: cancel the run.

    Only the first signal cancels; later ones are ignored so they can't interrupt the
    shutdown that saves the session.
    """
    loop = asyncio.get_running_loop()
    main = asyncio.current_task()
    assert main is not None
    _termination.clear()

    def on_signal(signum: int) -> None:
        if not _termination:
            _termination.append(signum)
            main.cancel()

    for sig in (signal.SIGTERM, signal.SIGHUP):
        loop.add_signal_handler(sig, on_signal, sig)


def _interrupted_exit_code() -> int:
    """Shell convention: 128 + signal number (130 for Ctrl-C, 143 for SIGTERM)."""
    return 128 + (_termination[0] if _termination else signal.SIGINT)


async def _run(
    target: str, kind: SessionKind, protocol: str, max_hops: int, cycles: int, json_out: bool
) -> int:
    _stop_on_termination()
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
        print(json.dumps({"id": sid, **final.to_dict(), "summary": summarize(final).to_dict()}))
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
                live.update(render_trace_with_summary(state))
                final = state
    assert final is not None
    return final


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


_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def run_server(web_app, host: str, port: int) -> None:
    uvicorn.run(web_app, host=host, port=port, log_level="info")


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Interface to listen on. Keep 127.0.0.1 unless you mean to share it.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8080,
    trusted_host: Annotated[
        list[str] | None,
        typer.Option("--trusted-host", help="Host name the UI may be reached as (repeatable). "
                     "Default: localhost/127.0.0.1 on loopback, any name when --host exposes it."),
    ] = None,
) -> None:
    """Start the web UI."""
    settings = Settings.from_env()
    geo = GeoLookup.open(settings.geo_dir)
    manager = SessionManager(make_engine(), geo, TraceRepository(init_db(settings.db_path)))
    static_dir = settings.static_dir if (settings.static_dir / "index.html").is_file() else None
    if static_dir is None:
        err().print("[yellow]Web UI is not built — run `npx -y pnpm@10.34.6 --dir frontend build`. "
                    "Serving the API only.[/yellow]")
    # Loopback: only answer to local Host names (blocks DNS rebinding). Exposed on purpose: any Host,
    # with cross-site requests still refused by the same-origin check.
    if trusted_host:
        allowed_hosts = tuple(trusted_host)
    else:
        allowed_hosts = LOCAL_HOSTS if host in _LOOPBACK else ("*",)
    if host not in _LOOPBACK:
        if allowed_hosts == ("*",):
            err().print(f"[yellow]Listening on {host}: anyone on your network can start traces from this machine.[/yellow]")
        else:
            out().print(f"Listening on {host}, answering only to {', '.join(allowed_hosts)}")
    shown_host = allowed_hosts[0] if host not in _LOOPBACK and allowed_hosts != ("*",) else host
    out().print(f"traceviz UI: http://{shown_host}:{port}")
    web_app = create_app(manager, geo_available=geo.available, static_dir=static_dir, allowed_hosts=allowed_hosts)
    run_server(web_app, host, port)
