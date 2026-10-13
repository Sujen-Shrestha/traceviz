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
