import pytest

from traceviz.core.geo.lookup import GeoResult
from traceviz.core.sessions.state import HopStats, TraceState
from traceviz.core.sessions.summary import summarize

LOCAL = GeoResult("local")


def geo(city, cc, name, asn=None):
    return GeoResult("geo", lat=0.0, lon=0.0, city=city, country=cc, country_name=name, asn=asn)


def hop(n, ip, best, avg, geo_result, received=10, sent=10):
    return HopStats(index=n - 1, ip=ip, sent=sent, received=received, best_ms=best,
                    last_ms=avg, worst_ms=avg, sum_ms=avg * received, geo=geo_result)


def make_state(target_ip, hops, status="completed", target="example.net"):
    state = TraceState(target=target, target_ip=target_ip, protocol="icmp", kind="trace", status=status)
    state.hops_by_index = {h.index: h for h in hops}
    return state


AU = "Southbank", "AU", "Australia"


def australia_route():
    """The user's real trace from Nepal to mde.techtrums.net.au (destination never answered)."""
    return make_state("110.232.143.134", [
        hop(1, "192.168.1.254", 1.4, 2.0, LOCAL),
        hop(2, "10.16.0.2", 3.1, 7.6, LOCAL),
        hop(3, "103.186.196.182", 3.5, 7.0, geo("Patan", "NP", "Nepal", 141767)),
        hop(4, "125.18.8.17", 6.9, 13.5, geo("New Delhi", "IN", "India", 9498)),
        hop(5, "116.119.68.57", 155.3, 159.9, geo("Gurugram", "IN", "India", 9498)),
        hop(6, "195.66.226.214", 151.7, 153.9, geo("London", "GB", "United Kingdom")),
        hop(7, "103.30.216.84", 387.7, 389.8, geo(*AU)),
        hop(8, "103.30.216.38", 391.3, 394.7, geo(*AU)),
        hop(9, "103.30.216.92", 388.2, 390.4, geo(*AU)),
        hop(10, "103.30.218.220", 399.4, 403.2, geo(*AU)),
        hop(11, "103.30.218.217", 396.4, 400.2, geo(*AU)),
        hop(12, "103.30.216.42", 4447.3, 5602.4, geo(*AU), received=8),
        hop(13, "103.30.217.169", 399.2, 401.8, geo(*AU)),
        hop(14, "43.225.33.62", 397.2, 400.6, geo("Warragul", "AU", "Australia", 58511)),
        hop(15, "103.252.152.242", 394.6, 416.2, geo("Sydney", "AU", "Australia", 45638)),
    ], target="mde.techtrums.net.au")


def test_unanswered_destination_reports_last_reply():
    s = summarize(australia_route())
    assert s.reached is False
    assert s.hop_count == 15
    assert s.last_hop == 15 and s.last_ip == "103.252.152.242" and s.last_place == "Sydney, AU"
    assert s.last_avg_ms == pytest.approx(416.2)
    assert s.last_loss_pct == 0.0


def test_route_merges_repeated_countries_and_skips_local():
    assert summarize(australia_route()).countries == ["Nepal", "India", "United Kingdom", "Australia"]


def test_networks_merge_repeats_and_skip_unknown():
    assert summarize(australia_route()).asns == [141767, 9498, 58511, 45638]


def test_biggest_jumps_use_best_times():
    jumps = summarize(australia_route()).jumps
    assert [(j.from_hop, j.to_hop) for j in jumps] == [(6, 7), (4, 5)]
    assert jumps[0].delta_ms == pytest.approx(236.0)
    assert (jumps[0].from_place, jumps[0].to_place) == ("London, GB", "Southbank, AU")


def test_isolated_loss_and_spike_is_flagged_harmless():
    notes = summarize(australia_route()).notes
    assert [(n.hop, n.kind) for n in notes] == [(12, "harmless")]
    assert "20% loss and high latency" in notes[0].message


def test_loss_continuing_to_the_end_is_a_problem():
    state = make_state("9.9.9.9", [
        hop(1, "10.0.0.1", 1, 1, LOCAL),
        hop(2, "1.0.0.2", 5, 6, None, received=10),
        hop(3, "1.0.0.3", 8, 9, None, received=7),
        hop(4, "1.0.0.4", 9, 10, None, received=6),
        hop(5, "9.9.9.9", 10, 11, None, received=7),
    ])
    s = summarize(state)
    assert s.reached is True and s.last_loss_pct == pytest.approx(30.0)
    assert [(n.hop, n.kind) for n in s.notes] == [(3, "problem")]
    assert "starts at hop 3" in s.notes[0].message


def test_small_jumps_are_ignored_and_silent_hops_skipped():
    state = make_state("9.9.9.9", [
        hop(1, "10.0.0.1", 1, 1, LOCAL),
        HopStats(index=1, sent=10),
        hop(3, "9.9.9.9", 15, 16, None),
    ])
    s = summarize(state)
    assert s.jumps == []
    assert s.notes == []
    assert s.hop_count == 3


def test_no_answers_yet():
    s = summarize(make_state("9.9.9.9", [], status="running"))
    assert s.last_hop is None and s.reached is False and s.countries == [] and s.jumps == []


def test_to_dict():
    d = summarize(australia_route()).to_dict()
    assert d["reached"] is False and d["last_hop"] == 15
    assert d["jumps"][0] == {"from_hop": 6, "to_hop": 7, "from_place": "London, GB",
                             "to_place": "Southbank, AU", "delta_ms": 236.0}
    assert d["notes"][0]["kind"] == "harmless"
