from rich.console import Console

from tests.fakes import fixture_events
from traceviz.cli.render import format_location, render_trace
from traceviz.core.geo.lookup import GeoResult
from traceviz.core.sessions.state import TraceState


def rendered(state) -> str:
    console = Console(record=True, width=200)
    console.print(render_trace(state))
    return console.export_text()


def test_format_location():
    assert format_location(None) == ""
    assert format_location(GeoResult("local")) == "local"
    assert format_location(GeoResult("unknown")) == "unknown location"
    assert format_location(GeoResult("geo", 1, 2, "London", "GB")) == "London, GB"
    assert format_location(GeoResult("geo", 1, 2, None, "AU", approximate=True)) == "AU ~approx"


def test_render_shows_hops_silent_rows_and_status():
    state = TraceState("1.1.1.1", "1.1.1.1", "icmp", "trace")
    for e in fixture_events():
        state.apply(e)
    state.hops_by_index[8].geo = GeoResult("geo", 1, 2, "Sydney", "AU", asn=13335, approximate=True)
    text = rendered(state)
    assert "trace to 1.1.1.1 (1.1.1.1) · ICMP · running" in text
    assert "_gateway (10.100.0.1)" in text
    assert "no reply" in text
    assert "Sydney, AU ~approx" in text
    assert "AS13335" in text
    assert "1314.0" in text  # hop 1 average
