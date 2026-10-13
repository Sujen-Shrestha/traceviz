import gzip
from datetime import date

import httpx
import pytest
import respx

from traceviz.core.geo.download import GeoDownloadError, download_latest

URL = "https://download.db-ip.com/free/dbip-{kind}-lite-{month}.mmdb.gz"


def serve(month, status=200):
    for kind in ("city", "asn"):
        respx.get(URL.format(kind=kind, month=month)).respond(
            status, content=gzip.compress(f"{kind}-{month}".encode()) if status == 200 else b""
        )


@respx.mock
def test_downloads_current_month(tmp_path):
    serve("2026-10")
    with httpx.Client() as client:
        month = download_latest(tmp_path / "geo", client, date(2026, 10, 13))
    assert month == "2026-10"
    assert (tmp_path / "geo" / "dbip-city-lite.mmdb").read_bytes() == b"city-2026-10"
    assert (tmp_path / "geo" / "dbip-asn-lite.mmdb").read_bytes() == b"asn-2026-10"


@respx.mock
def test_falls_back_to_previous_month_across_year(tmp_path):
    serve("2027-01", status=404)
    serve("2026-12")
    with httpx.Client() as client:
        assert download_latest(tmp_path, client, date(2027, 1, 2)) == "2026-12"
    assert (tmp_path / "dbip-city-lite.mmdb").read_bytes() == b"city-2026-12"


@respx.mock
def test_gives_up_after_two_missing_months(tmp_path):
    serve("2026-10", status=404)
    serve("2026-09", status=404)
    with httpx.Client() as client, pytest.raises(GeoDownloadError):
        download_latest(tmp_path, client, date(2026, 10, 1))


@respx.mock
def test_server_error_propagates(tmp_path):
    serve("2026-10", status=500)
    with httpx.Client() as client, pytest.raises(httpx.HTTPStatusError):
        download_latest(tmp_path, client, date(2026, 10, 13))
