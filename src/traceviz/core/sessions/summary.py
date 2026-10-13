"""Plain-language summary of a trace: where it went, where latency grew, what looks wrong."""

from dataclasses import asdict, dataclass, field
from typing import Literal

from traceviz.core.geo.lookup import GeoResult
from traceviz.core.sessions.state import HopStats, TraceState

LOSS_THRESHOLD_PCT = 10.0
MIN_JUMP_MS = 20.0
MAX_JUMPS = 2


@dataclass(frozen=True)
class LatencyJump:
    from_hop: int
    to_hop: int
    from_place: str | None
    to_place: str | None
    delta_ms: float


@dataclass(frozen=True)
class HopNote:
    hop: int
    kind: Literal["harmless", "problem"]
    message: str


@dataclass(frozen=True)
class TraceSummary:
    target: str
    status: str
    reached: bool
    hop_count: int
    last_hop: int | None = None
    last_ip: str | None = None
    last_place: str | None = None
    last_avg_ms: float | None = None
    last_loss_pct: float | None = None
    countries: list[str] = field(default_factory=list)
    asns: list[int] = field(default_factory=list)
    jumps: list[LatencyJump] = field(default_factory=list)
    notes: list[HopNote] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        for j in d["jumps"]:
            j["delta_ms"] = round(j["delta_ms"], 1)
        if d["last_avg_ms"] is not None:
            d["last_avg_ms"] = round(d["last_avg_ms"], 3)
        return d


def _place(geo: GeoResult | None) -> str | None:
    if geo is None or geo.status != "geo":
        return None
    if geo.city:
        return ", ".join(p for p in (geo.city, geo.country) if p)
    return geo.country_name or geo.country


def _dedupe(values: list) -> list:
    return [v for i, v in enumerate(values) if i == 0 or v != values[i - 1]]


def _jumps(answering: list[HopStats]) -> list[LatencyJump]:
    timed = [h for h in answering if h.best_ms is not None]
    # Latency only counts if it persists: a hop's floor is the lowest best time from it onward,
    # so a router that is merely slow to answer probes doesn't register as a jump.
    floors: list[float] = []
    for h in reversed(timed):
        floors.append(h.best_ms if not floors else min(h.best_ms, floors[-1]))
    floors.reverse()
    jumps = []
    for i in range(1, len(timed)):
        delta = floors[i] - floors[i - 1]
        if delta >= MIN_JUMP_MS:
            prev, cur = timed[i - 1], timed[i]
            jumps.append(LatencyJump(prev.index + 1, cur.index + 1, _place(prev.geo), _place(cur.geo), delta))
    jumps.sort(key=lambda j: j.delta_ms, reverse=True)
    return jumps[:MAX_JUMPS]


def _notes(answering: list[HopStats]) -> list[HopNote]:
    if len(answering) < 2:
        return []
    last = answering[-1]
    notes: list[HopNote] = []
    problem_start = None
    if last.loss_pct >= LOSS_THRESHOLD_PCT:
        problem_start = len(answering) - 1
        while problem_start > 0 and answering[problem_start - 1].loss_pct >= LOSS_THRESHOLD_PCT:
            problem_start -= 1
    end = problem_start if problem_start is not None else len(answering) - 1
    last_avg = last.avg_ms
    for h in answering[:end]:
        lossy = h.loss_pct >= LOSS_THRESHOLD_PCT
        spiky = (
            h.avg_ms is not None and last_avg is not None
            and h.avg_ms > 2 * last_avg and h.avg_ms - last_avg > 50
        )
        if not (lossy or spiky):
            continue
        what = " and ".join(
            p for p, on in ((f"{h.loss_pct:.0f}% loss", lossy), ("high latency", spiky)) if on
        )
        notes.append(HopNote(
            h.index + 1, "harmless",
            f"hop {h.index + 1}: {what} doesn't carry on to later hops — "
            "that router is likely just slow to answer probes (harmless).",
        ))
    if problem_start is not None:
        start = answering[problem_start].index + 1
        notes.append(HopNote(
            start, "problem",
            f"packet loss starts at hop {start} and continues to the last hop "
            f"({last.loss_pct:.0f}% there) — a real problem from hop {start} onward.",
        ))
    return notes


def summarize(state: TraceState) -> TraceSummary:
    hops = state.hops
    answering = [h for h in hops if h.ip is not None]
    base = dict(target=state.target, status=state.status,
                reached=state.destination_index is not None, hop_count=len(hops))
    if not answering:
        return TraceSummary(**base)
    last = answering[-1]
    return TraceSummary(
        **base,
        last_hop=last.index + 1,
        last_ip=last.ip,
        last_place=_place(last.geo),
        last_avg_ms=last.avg_ms,
        last_loss_pct=last.loss_pct,
        countries=_dedupe([g.country_name or g.country for h in answering
                           if (g := h.geo) and g.status == "geo" and (g.country_name or g.country)]),
        asns=_dedupe([h.geo.asn for h in answering if h.geo and h.geo.asn]),
        jumps=_jumps(answering),
        notes=_notes(answering),
    )
