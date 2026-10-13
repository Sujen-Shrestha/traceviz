import pytest

from tests.fakes import fixture_events
from traceviz.core.geo.lookup import GeoResult
from traceviz.core.probe.events import HopEvent
from traceviz.core.sessions.state import TraceState


def new_state(target_ip="1.1.1.1", kind="trace"):
    return TraceState(target="1.1.1.1", target_ip=target_ip, protocol="icmp", kind=kind)


def replay(state, events):
    for e in events:
        state.apply(e)
    return state


def test_hop_zero_statistics_from_real_capture():
    hop = replay(new_state(), fixture_events()).hops_by_index[0]
    assert hop.ip == "10.100.0.1"
    assert hop.hostname == "_gateway"
    assert (hop.sent, hop.received) == (3, 3)
    assert hop.last_ms == pytest.approx(1191.991)
    assert hop.best_ms == pytest.approx(902.388)
    assert hop.worst_ms == pytest.approx(1847.652)
    assert hop.avg_ms == pytest.approx(1314.010333, rel=1e-6)
    # mean absolute difference of consecutive RTTs: (945.264 + 655.661) / 2
    assert hop.jitter_ms == pytest.approx(800.4625)
    assert hop.loss_pct == 0.0


def test_hops_stop_at_first_destination_index_despite_out_of_order_replies():
    state = replay(new_state(), fixture_events())
    assert state.destination_index == 8
    assert [h.index for h in state.hops] == list(range(9))


def test_silent_hops_are_kept_with_full_loss():
    state = replay(new_state(), fixture_events())
    silent = [h for h in state.hops if h.ip is None]
    assert [h.index for h in silent] == [4, 6]
    assert all(h.loss_pct == 100.0 and h.avg_ms is None for h in silent)


def test_trailing_silent_hops_trimmed_when_destination_not_reached():
    state = replay(
        new_state(target_ip="9.9.9.9"),
        [HopEvent("sent", 0), HopEvent("host", 0, ip="10.0.0.1"), HopEvent("reply", 0, rtt_ms=1.0),
         HopEvent("sent", 1), HopEvent("sent", 2)],
    )
    assert [h.index for h in state.hops] == [0]
    state.status = "completed"
    assert state.suggest_other_protocol is True


def test_no_protocol_suggestion_while_running_or_when_reached():
    running = replay(new_state(target_ip="9.9.9.9"), [HopEvent("sent", 0)])
    assert running.suggest_other_protocol is False
    done = replay(new_state(), fixture_events())
    done.status = "completed"
    assert done.suggest_other_protocol is False


def test_new_ip_at_same_hop_clears_geo():
    state = new_state()
    hop = state.apply(HopEvent("host", 2, ip="8.8.8.8"))
    hop.geo = GeoResult("geo", lat=1.0, lon=2.0)
    state.apply(HopEvent("host", 2, ip="8.8.8.8"))
    assert hop.geo is not None
    state.apply(HopEvent("host", 2, ip="8.8.4.4"))
    assert hop.ip == "8.8.4.4" and hop.geo is None


def test_unsent_hop_has_zero_loss():
    hop = new_state().apply(HopEvent("host", 0, ip="10.0.0.1"))
    assert hop.loss_pct == 0.0


def test_snapshot_is_independent_copy():
    state = replay(new_state(), fixture_events())
    snap = state.snapshot()
    state.apply(HopEvent("sent", 0))
    assert snap.hops_by_index[0].sent == 3


def test_to_dict_uses_one_based_hop_numbers():
    state = replay(new_state(), fixture_events())
    state.hops_by_index[8].geo = GeoResult("geo", lat=-33.9, lon=151.2, city="Sydney", country="AU",
                                           asn=13335, org="Cloudflare", approximate=True)
    d = state.to_dict()
    assert d["destination_reached"] is True
    assert [h["hop"] for h in d["hops"]] == list(range(1, 10))
    assert d["hops"][8]["geo"]["city"] == "Sydney"
    assert d["hops"][4]["ip"] is None and d["hops"][4]["loss_pct"] == 100.0
