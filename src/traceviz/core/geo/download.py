import gzip
from datetime import date, timedelta
from pathlib import Path

import httpx

from traceviz.core.geo.lookup import ASN_DB, CITY_DB

ATTRIBUTION = "IP geolocation by DB-IP (https://db-ip.com), licensed CC BY 4.0"
_URL = "https://download.db-ip.com/free/dbip-{kind}-lite-{month}.mmdb.gz"
_FILES = {"city": CITY_DB, "asn": ASN_DB}


class GeoDownloadError(RuntimeError):
    """DB-IP Lite databases could not be downloaded."""


def _previous_month(d: date) -> date:
    return d.replace(day=1) - timedelta(days=1)


def _download_month(dest: Path, client: httpx.Client, month: str) -> None:
    payloads: dict[str, bytes] = {}
    for kind, filename in _FILES.items():
        resp = client.get(_URL.format(kind=kind, month=month), follow_redirects=True)
        resp.raise_for_status()
        payloads[filename] = gzip.decompress(resp.content)
    dest.mkdir(parents=True, exist_ok=True)
    for filename, data in payloads.items():
        tmp = dest / f"{filename}.tmp"
        tmp.write_bytes(data)
        tmp.replace(dest / filename)


def download_latest(dest: Path, client: httpx.Client, today: date) -> str:
    for d in (today, _previous_month(today)):
        month = d.strftime("%Y-%m")
        try:
            _download_month(dest, client, month)
            return month
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise
    raise GeoDownloadError("DB-IP Lite databases are not available for this or last month")
