from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from traceviz.core.geo.lookup import GeoResult
from traceviz.core.sessions.state import HopStats, TraceState
from traceviz.core.sessions.summary import TraceSummary, summarize

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


def _result_line(s: TraceSummary) -> tuple[str, str]:
    stats = f"{_ms0(s.last_avg_ms)} avg · {s.last_loss_pct:.0f}% loss"
    if s.reached:
        return "Reached", f"{s.target} in {s.hop_count} hops · {stats}"
    where = s.last_place or s.last_ip
    last = f"last reply from hop {s.last_hop} ({where}) · {stats}"
    if s.status == "running":
        return "Tracing", f"{s.target} · {last}"
    return "No reply", f"{s.target} didn't answer · {last}"


def _ms0(v: float | None) -> str:
    return "—" if v is None else f"{v:.0f} ms"


def render_summary(s: TraceSummary) -> RenderableType:
    if s.last_hop is None:
        return Text("Summary: No hops have answered yet.", style="dim")
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold")
    grid.add_column()
    grid.add_row(*_result_line(s))
    if s.countries:
        grid.add_row("Route", " → ".join(s.countries))
    if s.asns:
        grid.add_row("Networks", " → ".join(f"AS{a}" for a in s.asns))
    for i, j in enumerate(s.jumps):
        places = f"{j.from_place or '?'} → {j.to_place or '?'}"
        grid.add_row("Biggest jumps" if i == 0 else "",
                     f"hop {j.from_hop} → {j.to_hop}   {places}   [bold]+{j.delta_ms:.0f} ms[/bold]")
    for i, n in enumerate(s.notes):
        style = "red" if n.kind == "problem" else "yellow"
        grid.add_row("Notes" if i == 0 else "", f"[{style}]{n.message}[/{style}]")
    return Group(Text("Summary", style="bold underline"), grid)


def render_trace_with_summary(state: TraceState) -> RenderableType:
    return Group(render_trace(state), Text(""), render_summary(summarize(state)))
