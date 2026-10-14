from rich.console import Console

from tests.fakes import fixture_events
from tests.core.test_summary import australia_route
from traceviz.cli.render import format_location, render_summary, render_trace
from traceviz.core.geo.lookup import GeoResult
from traceviz.core.probe.events import HopEvent
from traceviz.core.sessions.state import TraceState
from traceviz.core.sessions.summary import summarize


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


def rendered_summary(state) -> str:
    console = Console(record=True, width=200)
    console.print(render_summary(summarize(state)))
    return console.export_text()


def test_render_summary_unanswered_destination():
    text = rendered_summary(australia_route())
    assert "Summary" in text
    assert "mde.techtrums.net.au didn't answer · last reply from hop 15 (Sydney, AU) · 416 ms avg · 0% loss" in text
    assert "Nepal → India → United Kingdom → Australia" in text
    assert "AS141767 → AS9498 → AS58511 → AS45638" in text
    assert "hop 6 → 7" in text and "London, GB → Southbank, AU" in text and "+236 ms" in text
    assert "hop 12: 20% loss and high latency" in text


def test_render_summary_reached_and_no_replies():
    state = TraceState("1.1.1.1", "1.1.1.1", "icmp", "trace", status="completed")
    for e in fixture_events():
        state.apply(e)
    assert "Reached" in rendered_summary(state) and "1.1.1.1 in 9 hops" in rendered_summary(state)
    empty = TraceState("x.com", "9.9.9.9", "icmp", "trace")
    assert "No hops have answered yet" in rendered_summary(empty)


def test_markup_in_hostnames_and_places_is_shown_literally():
    state = TraceState("x", "9.9.9.9", "icmp", "trace")
    hop = state.apply(HopEvent("host", 0, ip="203.0.113.7"))
    state.apply(HopEvent("dns", 0, hostname="evil[/x][link=http://bad]"))
    hop.geo = GeoResult("geo", 1, 2, "[bold]Town", "AU")
    text = rendered(state)
    assert "evil[/x][link=http://bad] (203.0.113.7)" in text
    assert "[bold]Town, AU" in text
