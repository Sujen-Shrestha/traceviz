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
