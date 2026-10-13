import ipaddress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

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
