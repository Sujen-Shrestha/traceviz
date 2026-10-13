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
