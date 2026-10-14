import pytest

from tests.fakes import DictReader
from traceviz.core.geo.lookup import GeoLookup, GeoResult

CITY = {
    "8.8.8.8": {
        "city": {"names": {"en": "Mountain View"}},
        "country": {"iso_code": "US", "names": {"en": "United States"}},
        "location": {"latitude": 37.386, "longitude": -122.0838},
    },
    "81.2.69.160": {
        "city": {"names": {"en": "London"}},
        "country": {"iso_code": "GB", "names": {"en": "United Kingdom"}},
        "location": {"latitude": 51.5142, "longitude": -0.0931},
    },
    "45.127.172.45": {
        "country": {"iso_code": "AU", "names": {"en": "Australia"}},
        "location": {"latitude": -33.494, "longitude": 143.2104},
    },
}
ASN = {
    "8.8.8.8": {"autonomous_system_number": 15169, "autonomous_system_organization": "Google LLC"},
    "81.2.69.160": {"autonomous_system_number": 20712, "autonomous_system_organization": "Andrews & Arnold"},
    "5.5.5.5": {"autonomous_system_number": 6805, "autonomous_system_organization": "Telefonica"},
}


@pytest.fixture
def geo():
    return GeoLookup(city=DictReader(CITY), asn=DictReader(ASN))


@pytest.mark.parametrize(
    "ip", ["10.0.0.1", "192.168.65.3", "100.64.0.8", "127.0.0.1", "169.254.1.1", "fe80::1", "fd00::1"]
)
def test_non_global_addresses_are_local(geo, ip):
    assert geo.lookup(ip) == GeoResult("local")


def test_city_level_result(geo):
    r = geo.lookup("81.2.69.160")
    assert r == GeoResult("geo", 51.5142, -0.0931, "London", "GB", "United Kingdom", 20712,
                          "Andrews & Arnold", approximate=False)


def test_anycast_asn_is_approximate(geo):
    r = geo.lookup("8.8.8.8")
    assert r.status == "geo" and r.city == "Mountain View" and r.asn == 15169 and r.approximate


def test_country_only_result_is_approximate(geo):
    r = geo.lookup("45.127.172.45")
    assert r.status == "geo" and r.city is None and r.country == "AU" and r.approximate


def test_unknown_location_keeps_asn(geo):
    assert geo.lookup("5.5.5.5") == GeoResult("unknown", asn=6805, org="Telefonica")


def test_unknown_everything(geo):
    assert geo.lookup("1.0.0.1") == GeoResult("unknown")


def test_open_with_missing_files_is_unavailable_but_works(tmp_path):
    geo = GeoLookup.open(tmp_path / "nope")
    assert geo.available is False
    assert geo.lookup("8.8.8.8") == GeoResult("unknown")
    assert geo.lookup("10.0.0.1") == GeoResult("local")


def test_corrupt_database_is_treated_as_missing(tmp_path, caplog):
    (tmp_path / "dbip-city-lite.mmdb").write_bytes(b"not a maxmind database")
    (tmp_path / "dbip-asn-lite.mmdb").write_bytes(b"\x00" * 10)
    geo = GeoLookup.open(tmp_path)
    assert geo.available is False
    assert geo.lookup("8.8.8.8") == GeoResult("unknown")
    assert "could not open" in caplog.text
