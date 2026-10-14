import asyncio
import sqlite3
import threading

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


async def test_unexpected_error_marks_failed_and_ends_subscribers(repo):
    engine = FakeEngine(fixture_events()[:20], error=RuntimeError("boom"))
    mgr = make(repo, engine)
    sid = await mgr.start(TARGET)
    states = [s async for s in mgr.subscribe(sid)]
    assert states[-1].status == "failed" and states[-1].error == "RuntimeError: boom"
    assert repo.get_trace(sid)[0].status == "failed"


class RecordingRepo(TraceRepository):
    """Records which threads repository methods run on."""

    def __init__(self, engine):
        super().__init__(engine)
        self.threads: set[int] = set()

    def create_trace(self, *args):
        self.threads.add(threading.get_ident())
        return super().create_trace(*args)

    def finish_trace(self, *args):
        self.threads.add(threading.get_ident())
        return super().finish_trace(*args)

    def add_monitor_samples(self, rows):
        self.threads.add(threading.get_ident())
        return super().add_monitor_samples(rows)


class FlakyRepo(TraceRepository):
    def __init__(self, engine):
        super().__init__(engine)
        self.failures_left = 1

    def add_monitor_samples(self, rows):
        if self.failures_left:
            self.failures_left -= 1
            raise sqlite3.OperationalError("database is locked")
        super().add_monitor_samples(rows)


async def test_repository_calls_run_off_the_event_loop(tmp_path):
    repo = RecordingRepo(init_db(tmp_path / "r.db"))
    mgr = make(repo, FakeEngine(fixture_events() * 2, delay=0.001), sample_interval_s=0.02)
    await mgr.wait(await mgr.start(TARGET, kind="monitor"))
    assert repo.threads and threading.get_ident() not in repo.threads


async def test_sample_write_failure_is_logged_and_totals_still_add_up(tmp_path, caplog):
    repo = FlakyRepo(init_db(tmp_path / "f.db"))
    mgr = make(repo, FakeEngine(fixture_events() * 3, delay=0.001), sample_interval_s=0.02)
    sid = await mgr.start(TARGET, kind="monitor")
    final = await mgr.wait(sid)
    assert final.status == "completed"
    assert "could not save monitor samples" in caplog.text
    samples = repo.monitor_samples(sid)
    for hop in final.hops:
        assert sum(s.sent for s in samples if s.hop_index == hop.index) == hop.sent


async def test_concurrent_starts_respect_the_limit(repo):
    mgr = make(repo, FakeEngine([], hang=True), max_sessions=1)
    results = await asyncio.gather(mgr.start(TARGET), mgr.start(TARGET), return_exceptions=True)
    assert sum(isinstance(r, TooManySessions) for r in results) == 1
    await mgr.close()


async def test_snapshot(repo):
    mgr = make(repo, FakeEngine(fixture_events()))
    sid = await mgr.start(TARGET)
    await mgr.wait(sid)
    assert mgr.snapshot(sid).status == "completed"
    with pytest.raises(SessionNotFound):
        mgr.snapshot(999)



class SlowFinishRepo(TraceRepository):
    def finish_trace(self, *args):
        import time

        time.sleep(0.2)  # a busy database while the subscriber is being torn down
        return super().finish_trace(*args)


async def test_cancelling_the_stopper_does_not_interrupt_the_session_save(tmp_path):
    # A WebSocket handler that is cancelled again while it waits in stop() must not
    # cancel the session task halfway through saving its final state.
    repo = SlowFinishRepo(init_db(tmp_path / "s.db"))
    engine = FakeEngine(fixture_events()[:5], hang=True)
    mgr = make(repo, engine)
    sid = await mgr.start(TARGET, kind="monitor")

    async def consume():
        async for _ in mgr.subscribe(sid):
            pass

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    consumer.cancel()  # subscriber leaves -> stop() begins, session starts saving
    await asyncio.sleep(0.05)
    consumer.cancel()  # cancelled again while stop() is waiting on the save
    await asyncio.gather(consumer, return_exceptions=True)
    final = await asyncio.wait_for(mgr.wait(sid), 2)
    assert final.status == "stopped"
    assert repo.get_trace(sid)[0].status == "stopped"
    assert engine.running == 0


class SlowSamplesRepo(TraceRepository):
    def add_monitor_samples(self, rows):
        import time

        time.sleep(0.15)  # still writing when the monitor ends and the sampler is cancelled
        super().add_monitor_samples(rows)


async def test_sampler_cancelled_mid_write_does_not_double_count(tmp_path):
    repo = SlowSamplesRepo(init_db(tmp_path / "w.db"))
    mgr = make(repo, FakeEngine(fixture_events(), delay=0.001), sample_interval_s=0.02)
    sid = await mgr.start(TARGET, kind="monitor")
    final = await mgr.wait(sid)
    await asyncio.sleep(0.3)  # let any in-flight write land
    samples = repo.monitor_samples(sid)
    for hop in final.hops:
        assert sum(s.sent for s in samples if s.hop_index == hop.index) == hop.sent
        assert sum(s.received for s in samples if s.hop_index == hop.index) == hop.received


class CountingSlowFinishRepo(TraceRepository):
    def __init__(self, engine):
        super().__init__(engine)
        self.finish_calls = 0

    def finish_trace(self, *args):
        import time

        self.finish_calls += 1
        time.sleep(0.2)
        return super().finish_trace(*args)


async def test_overlapping_stops_save_exactly_once(tmp_path):
    repo = CountingSlowFinishRepo(init_db(tmp_path / "o.db"))
    mgr = make(repo, FakeEngine(fixture_events()[:5], hang=True))
    sid = await mgr.start(TARGET, kind="monitor")
    first = asyncio.create_task(mgr.stop(sid))
    await asyncio.sleep(0.05)  # first stop is mid-save
    await asyncio.gather(mgr.stop(sid), mgr.close(), first)
    assert repo.finish_calls == 1
    assert (await mgr.wait(sid)).status == "stopped"
    assert len(repo.list_traces()) == 1


async def test_unwatched_session_is_stopped_after_grace_period(repo):
    engine = FakeEngine(fixture_events()[:5], hang=True)
    mgr = make(repo, engine, subscriber_grace_s=0.05)
    sid = await mgr.start(TARGET, kind="monitor")
    final = await asyncio.wait_for(mgr.wait(sid), 2)
    assert final.status == "stopped" and engine.running == 0


async def test_watched_session_outlives_grace_period(repo):
    mgr = make(repo, FakeEngine(fixture_events()[:5], hang=True), subscriber_grace_s=0.05)
    sid = await mgr.start(TARGET, kind="monitor")
    gen = mgr.subscribe(sid)
    await anext(gen)
    await asyncio.sleep(0.15)
    assert mgr.snapshot(sid).status == "running"
    await gen.aclose()
    await mgr.close()


async def test_close_does_not_wait_for_grace_timers(repo):
    mgr = make(repo, FakeEngine(fixture_events()), subscriber_grace_s=60)
    await mgr.wait(await mgr.start(TARGET))
    await asyncio.wait_for(mgr.close(), 1)


async def test_finished_sessions_are_evicted_beyond_the_cap(repo):
    mgr = make(repo, FakeEngine(fixture_events()), max_finished=2)
    ids = [await mgr.start(TARGET) for _ in range(1)]
    for _ in range(3):
        await mgr.wait(ids[-1])
        ids.append(await mgr.start(TARGET))
    await mgr.wait(ids[-1])
    with pytest.raises(SessionNotFound):
        mgr.snapshot(ids[0])
    assert mgr.snapshot(ids[-1]).status == "completed"
    assert repo.get_trace(ids[0])[0].status == "completed"  # still in history

