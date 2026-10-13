import json

import pytest
from typer.testing import CliRunner

from tests.fakes import FakeEngine, fixture_events
from traceviz.cli import app as cli
from traceviz.core.probe.engine import ProbeError
from traceviz.core.probe.events import HopEvent
from traceviz.core.probe.target import InvalidTarget, ResolvedTarget
from traceviz.core.store.repo import TraceRepository, init_db

runner = CliRunner()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "resolve_target", lambda t: ResolvedTarget(t, "1.1.1.1"))
    return {"TRACEVIZ_DATA_DIR": str(tmp_path), "TRACEVIZ_GEO_DIR": str(tmp_path / "nogeo"),
            "COLUMNS": "200"}


def use_engine(monkeypatch, engine):
    monkeypatch.setattr(cli, "make_engine", lambda: engine)
    return engine


def test_trace_prints_table_and_persists(env, monkeypatch, tmp_path):
    use_engine(monkeypatch, FakeEngine(fixture_events()))
    result = runner.invoke(cli.app, ["trace", "one.one.one.one"], env=env)
    assert result.exit_code == 0, result.output
    assert "10.100.0.1" in result.output
    assert "completed" in result.output
    assert "traceviz fetch-geo" in result.output  # missing geo DB warning
    assert "Summary" in result.output and "Reached" in result.output
    traces = TraceRepository(init_db(tmp_path / "traceviz.db")).list_traces()
    assert [t.status for t in traces] == ["completed"]


def test_trace_json_output(env, monkeypatch):
    engine = use_engine(monkeypatch, FakeEngine(fixture_events()))
    result = runner.invoke(
        cli.app, ["trace", "one.one.one.one", "--json", "-p", "tcp", "--max-hops", "20", "--cycles", "3"], env=env
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert engine.calls == [("1.1.1.1", "tcp", 20, 3)]
    assert data["id"] == 1 and data["status"] == "completed" and data["destination_reached"] is True
    assert [h["hop"] for h in data["hops"]] == list(range(1, 10))
    assert data["summary"]["reached"] is True and data["summary"]["last_hop"] == 9
    assert set(data["hops"][0]) == {"hop", "ip", "hostname", "sent", "received", "loss_pct", "last_ms",
                                    "avg_ms", "best_ms", "worst_ms", "jitter_ms", "geo"}
    assert data["hops"][0]["geo"] == {"status": "local", "lat": None, "lon": None, "city": None,
                                      "country": None, "country_name": None, "asn": None, "org": None,
                                      "approximate": False}


def test_invalid_target_exits_2_without_probing(env, monkeypatch):
    engine = use_engine(monkeypatch, FakeEngine([]))

    def reject(t):
        raise InvalidTarget(f"not a valid hostname or IP address: {t!r}")

    monkeypatch.setattr(cli, "resolve_target", reject)
    result = runner.invoke(cli.app, ["trace", "--", "--help"], env=env)
    assert result.exit_code == 2
    assert "not a valid hostname" in result.output
    assert engine.calls == []


def test_probe_failure_exits_1_with_hint(env, monkeypatch):
    use_engine(monkeypatch, FakeEngine([], error=ProbeError("mtr could not open raw sockets ... NET_RAW")))
    result = runner.invoke(cli.app, ["trace", "1.1.1.1"], env=env)
    assert result.exit_code == 1
    assert "NET_RAW" in result.output


def test_blocked_icmp_suggests_tcp(env, monkeypatch):
    events = [HopEvent("sent", 0), HopEvent("host", 0, ip="10.0.0.1"), HopEvent("reply", 0, rtt_ms=1.0),
              HopEvent("sent", 1), HopEvent("sent", 2)]
    use_engine(monkeypatch, FakeEngine(events))
    result = runner.invoke(cli.app, ["trace", "1.1.1.1"], env=env)
    assert result.exit_code == 0
    assert "--protocol tcp" in result.output


def test_monitor_runs_until_engine_ends(env, monkeypatch):
    engine = use_engine(monkeypatch, FakeEngine(fixture_events()))
    result = runner.invoke(cli.app, ["monitor", "1.1.1.1"], env=env)
    assert result.exit_code == 0, result.output
    assert engine.calls[0][3] is None
    assert "monitor to 1.1.1.1" in result.output


def test_history_lists_newest_first(env, monkeypatch):
    use_engine(monkeypatch, FakeEngine(fixture_events()))
    runner.invoke(cli.app, ["trace", "a.example"], env=env)
    runner.invoke(cli.app, ["trace", "b.example"], env=env)
    result = runner.invoke(cli.app, ["history", "--json"], env=env)
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert [r["target"] for r in rows] == ["b.example", "a.example"]
    assert rows[0]["status"] == "completed"
    filtered = json.loads(runner.invoke(cli.app, ["history", "--json", "--target", "a.example"], env=env).stdout)
    assert [r["target"] for r in filtered] == ["a.example"]


def test_history_table(env, monkeypatch):
    use_engine(monkeypatch, FakeEngine(fixture_events()))
    runner.invoke(cli.app, ["trace", "a.example"], env=env)
    result = runner.invoke(cli.app, ["history"], env=env)
    assert result.exit_code == 0 and "a.example" in result.output


def test_doctor_reports_ok(env, monkeypatch):
    use_engine(monkeypatch, FakeEngine([]))
    result = runner.invoke(cli.app, ["doctor"], env=env)
    assert result.exit_code == 0
    assert "mtr: ok" in result.output
    assert "geolocation: missing" in result.output


def test_doctor_reports_mtr_problem(env, monkeypatch):
    use_engine(monkeypatch, FakeEngine([], check_error=ProbeError("raw sockets ... NET_RAW")))
    result = runner.invoke(cli.app, ["doctor"], env=env)
    assert result.exit_code == 1
    assert "NET_RAW" in result.output


def test_fetch_geo(env, monkeypatch, tmp_path):
    calls = []

    def fake_download(dest, client, today):
        calls.append(dest)
        return "2026-10"

    monkeypatch.setattr(cli, "download_latest", fake_download)
    result = runner.invoke(cli.app, ["fetch-geo"], env=env)
    assert result.exit_code == 0
    assert calls == [tmp_path / "nogeo"]
    assert "2026-10" in result.output and "DB-IP" in result.output


def capture_server(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "run_server", lambda web_app, host, port: calls.append((web_app, host, port)))
    return calls


def test_serve_defaults_to_localhost(env, monkeypatch, tmp_path):
    use_engine(monkeypatch, FakeEngine([]))
    calls = capture_server(monkeypatch)
    result = runner.invoke(cli.app, ["serve"], env={**env, "TRACEVIZ_STATIC_DIR": str(tmp_path / "nodist")})
    assert result.exit_code == 0, result.output
    (_, host, port), = calls
    assert (host, port) == ("127.0.0.1", 8080)
    assert "http://127.0.0.1:8080" in result.output
    assert "Serving the API only" in result.output


def test_serve_warns_when_exposed(env, monkeypatch, tmp_path):
    use_engine(monkeypatch, FakeEngine([]))
    calls = capture_server(monkeypatch)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("ui")
    result = runner.invoke(cli.app, ["serve", "--host", "0.0.0.0", "--port", "9000"],
                           env={**env, "TRACEVIZ_STATIC_DIR": str(dist)})
    assert result.exit_code == 0
    assert calls[0][1:] == ("0.0.0.0", 9000)
    assert "anyone on your network" in result.output
    assert "Serving the API only" not in result.output
