import asyncio

import pytest

from tests.fakes import CITY_FIXTURE, DictReader, FakeEngine, fixture_events
from traceviz.core.geo.lookup import GeoLookup
from traceviz.core.probe.engine import ProbeError
from traceviz.core.probe.target import ResolvedTarget
from traceviz.core.sessions.manager import SessionManager, SessionNotFound, TooManySessions
from traceviz.core.store.repo import TraceRepository, init_db

TARGET = ResolvedTarget("one.one.one.one", "1.1.1.1")


@pytest.fixture
def repo(tmp_path):
    return TraceRepository(init_db(tmp_path / "t.db"))


def make(repo, engine, **kw):
    geo = GeoLookup(city=DictReader(CITY_FIXTURE), asn=None)
    return SessionManager(engine, geo, repo, **kw)


async def test_trace_completes_enriches_and_persists(repo):
    engine = FakeEngine(fixture_events())
    mgr = make(repo, engine)
    sid = await mgr.start(TARGET, protocol="udp", max_hops=20, cycles=3)
    final = await mgr.wait(sid)
    assert engine.calls == [("1.1.1.1", "udp", 20, 3)]
    assert final.status == "completed"
    assert len(final.hops) == 9
    assert final.hops[0].geo.status == "local"
    assert final.hops[8].geo.city == "Sydney"
    rec, hops = repo.get_trace(sid)
    assert rec.status == "completed" and rec.target == "one.one.one.one" and len(hops) == 9


async def test_subscribe_yields_snapshots_until_final(repo):
    mgr = make(repo, FakeEngine(fixture_events(), delay=0.001))
    sid = await mgr.start(TARGET)
    states = [s async for s in mgr.subscribe(sid)]
    assert states[0].status == "running"
    assert states[-1].status == "completed"
    assert len(states[-1].hops) == 9


async def test_subscribe_after_finish_yields_final_once(repo):
    mgr = make(repo, FakeEngine(fixture_events()))
    sid = await mgr.start(TARGET)
    await mgr.wait(sid)
    states = [s async for s in mgr.subscribe(sid)]
    assert [s.status for s in states] == ["completed"]


async def test_probe_error_marks_failed_and_keeps_partial_hops(repo):
    engine = FakeEngine(fixture_events()[:20], error=ProbeError("mtr exploded"))
    mgr = make(repo, engine)
    sid = await mgr.start(TARGET)
    final = await mgr.wait(sid)
    assert final.status == "failed" and final.error == "mtr exploded"
    rec, hops = repo.get_trace(sid)
    assert rec.status == "failed" and rec.error == "mtr exploded" and len(hops) > 0


async def test_trace_timeout(repo):
    engine = FakeEngine(fixture_events()[:5], hang=True)
    mgr = make(repo, engine, trace_timeout_s=0.05)
    final = await mgr.wait(await mgr.start(TARGET))
    assert final.status == "failed" and "timed out" in final.error
    assert engine.running == 0


async def test_stop_kills_probe_and_saves_stopped(repo):
    engine = FakeEngine(fixture_events()[:5], hang=True)
    mgr = make(repo, engine)
    sid = await mgr.start(TARGET)
    await asyncio.sleep(0.01)
    await mgr.stop(sid)
    assert engine.running == 0
    assert (await mgr.wait(sid)).status == "stopped"
    assert repo.get_trace(sid)[0].status == "stopped"


async def test_last_subscriber_leaving_stops_session(repo):
    engine = FakeEngine(fixture_events()[:5], hang=True)
    mgr = make(repo, engine)
    sid = await mgr.start(TARGET, kind="monitor")
    gen = mgr.subscribe(sid)
    await anext(gen)
    await gen.aclose()
    assert (await mgr.wait(sid)).status == "stopped"
    assert engine.running == 0


async def test_session_limit(repo):
    mgr = make(repo, FakeEngine([], hang=True), max_sessions=1)
    await mgr.start(TARGET)
    with pytest.raises(TooManySessions):
        await mgr.start(TARGET)
    await mgr.close()


async def test_finished_sessions_free_their_slot(repo):
    mgr = make(repo, FakeEngine(fixture_events()), max_sessions=1)
    await mgr.wait(await mgr.start(TARGET))
    await mgr.wait(await mgr.start(TARGET))


async def test_unknown_session(repo):
    mgr = make(repo, FakeEngine([]))
    with pytest.raises(SessionNotFound):
        await mgr.stop(42)


async def test_monitor_runs_unlimited_and_samples_add_up(repo):
    events = fixture_events() * 4
    engine = FakeEngine(events, delay=0.001)
    mgr = make(repo, engine, sample_interval_s=0.02)
    sid = await mgr.start(TARGET, kind="monitor", cycles=3)
    final = await mgr.wait(sid)
    assert engine.calls[0][3] is None
    samples = repo.monitor_samples(sid)
    assert len({s.ts for s in samples}) >= 2
    for hop in final.hops:
        hop_samples = [s for s in samples if s.hop_index == hop.index]
        assert sum(s.sent for s in hop_samples) == hop.sent
        assert sum(s.received for s in hop_samples) == hop.received
