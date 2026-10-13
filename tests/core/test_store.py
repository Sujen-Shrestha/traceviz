import sqlite3
from datetime import UTC, datetime

import pytest

from tests.fakes import fixture_events
from traceviz.core.geo.lookup import GeoResult
from traceviz.core.sessions.state import TraceState
from traceviz.core.store.models import MonitorSampleRecord
from traceviz.core.store.repo import TraceRepository, init_db

T0 = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 13, 8, 1, tzinfo=UTC)


@pytest.fixture
def repo(tmp_path):
    return TraceRepository(init_db(tmp_path / "nested" / "traceviz.db"))


def finished_state(target="1.1.1.1"):
    state = TraceState(target=target, target_ip="1.1.1.1", protocol="icmp", kind="trace")
    for e in fixture_events():
        state.apply(e)
    state.hops_by_index[8].geo = GeoResult("geo", lat=-33.9, lon=151.2, city="Sydney", country="AU",
                                           country_name="Australia", asn=13335, org="Cloudflare",
                                           approximate=True)
    state.status = "completed"
    return state


def test_init_db_creates_wal_database_with_version(tmp_path):
    path = tmp_path / "a" / "b" / "traceviz.db"
    init_db(path)
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert con.execute("PRAGMA user_version").fetchone()[0] == 1
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"traces", "hops", "monitor_samples"} <= tables


def test_init_db_is_idempotent(tmp_path):
    init_db(tmp_path / "x.db")
    init_db(tmp_path / "x.db")


def test_trace_roundtrip(repo):
    state = finished_state()
    tid = repo.create_trace(state, T0)
    repo.finish_trace(tid, state, T1)
    rec, hops = repo.get_trace(tid)
    assert (rec.target, rec.status, rec.kind, rec.protocol) == ("1.1.1.1", "completed", "trace", "icmp")
    assert rec.finished_at is not None
    assert [h.hop_index for h in hops] == list(range(9))
    assert hops[4].ip is None and hops[4].loss_pct == 100.0
    assert hops[0].avg_ms == pytest.approx(1314.010333, rel=1e-6)
    assert (hops[8].city, hops[8].asn, hops[8].approximate, hops[8].geo_status) == ("Sydney", 13335, True, "geo")


def test_finish_twice_does_not_duplicate_hops(repo):
    state = finished_state()
    tid = repo.create_trace(state, T0)
    repo.finish_trace(tid, state, T1)
    repo.finish_trace(tid, state, T1)
    assert len(repo.get_trace(tid)[1]) == 9


def test_get_missing_trace(repo):
    assert repo.get_trace(999) is None


def test_list_traces_newest_first_with_filter_and_limit(repo):
    ids = [repo.create_trace(finished_state(t), T0) for t in ["a.com", "b.com", "a.com"]]
    assert [r.id for r in repo.list_traces()] == ids[::-1]
    assert [r.id for r in repo.list_traces(target="a.com")] == [ids[2], ids[0]]
    assert len(repo.list_traces(limit=1)) == 1


def test_monitor_samples(repo):
    tid = repo.create_trace(finished_state(), T0)
    repo.add_monitor_samples([
        MonitorSampleRecord(trace_id=tid, ts=T0, hop_index=0, sent=10, received=9, avg_ms=12.5),
        MonitorSampleRecord(trace_id=tid, ts=T1, hop_index=0, sent=10, received=10, avg_ms=11.0),
    ])
    samples = repo.monitor_samples(tid)
    assert [(s.sent, s.received) for s in samples] == [(10, 9), (10, 10)]


from traceviz.core.store.repo import SchemaTooNew


def test_connections_wait_for_locks(tmp_path):
    engine = init_db(tmp_path / "t.db")
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000


def test_refuses_newer_schema(tmp_path):
    path = tmp_path / "t.db"
    init_db(path)
    con = sqlite3.connect(path)
    con.execute("PRAGMA user_version=99")
    con.commit()
    con.close()
    with pytest.raises(SchemaTooNew, match="v99"):
        init_db(path)
