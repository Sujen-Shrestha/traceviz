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
