from tests.fakes import FakeEngine, fixture_events
from tests.web.conftest import wait_for_status
from traceviz.core.probe.engine import ProbeError
from traceviz.core.probe.target import InvalidTarget


def test_health_reports_ready(make_client):
    body = make_client(FakeEngine([])).get("/api/health").json()
    assert body["probe_ok"] is True and body["probe_error"] is None
    assert body["geo_available"] is True and "DB-IP" in body["attribution"]


def test_health_reports_probe_problem(make_client):
    engine = FakeEngine([], check_error=ProbeError("mtr could not open raw sockets ... NET_RAW"))
    body = make_client(engine).get("/api/health").json()
    assert body["probe_ok"] is False and "NET_RAW" in body["probe_error"]


def test_start_trace_and_read_final_snapshot(make_client):
    engine = FakeEngine(fixture_events())
    client = make_client(engine)
    resp = client.post("/api/sessions", json={"target": "one.one.one.one", "protocol": "udp",
                                              "max_hops": 20, "cycles": 3})
    assert resp.status_code == 201
    created = resp.json()
    assert created == {"id": created["id"], "target": "one.one.one.one", "target_ip": "1.1.1.1"}
    body = wait_for_status(client, created["id"], {"completed"})
    assert engine.calls == [("1.1.1.1", "udp", 20, 3)]
    assert body["type"] == "state" and body["id"] == created["id"]
    assert len(body["hops"]) == 9 and body["hops"][8]["geo"]["city"] == "Sydney"
    assert body["summary"]["reached"] is True and body["summary"]["last_hop"] == 9
    assert body["suggest_other_protocol"] is False


def test_invalid_target_is_422_with_readable_detail(make_client):
    def reject(target):
        raise InvalidTarget(f"not a valid hostname or IP address: {target!r}")

    client = make_client(FakeEngine([]), resolve=reject)
    resp = client.post("/api/sessions", json={"target": "--help"})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "not a valid hostname or IP address: '--help'"


def test_out_of_range_options_are_422(make_client):
    client = make_client(FakeEngine([]))
    assert client.post("/api/sessions", json={"target": "a.com", "max_hops": 0}).status_code == 422
    assert client.post("/api/sessions", json={"target": "a.com", "protocol": "sctp"}).status_code == 422
    assert client.post("/api/sessions", json={"target": ""}).status_code == 422


def test_too_many_sessions_is_429(make_client):
    client = make_client(FakeEngine([], hang=True), max_sessions=1)
    assert client.post("/api/sessions", json={"target": "a.com"}).status_code == 201
    resp = client.post("/api/sessions", json={"target": "b.com"})
    assert resp.status_code == 429 and "at most 1" in resp.json()["detail"]


def test_stop_session(make_client):
    engine = FakeEngine(fixture_events()[:5], hang=True)
    client = make_client(engine)
    sid = client.post("/api/sessions", json={"target": "a.com", "kind": "monitor"}).json()["id"]
    assert client.post(f"/api/sessions/{sid}/stop").status_code == 204
    assert wait_for_status(client, sid, {"stopped"})["kind"] == "monitor"
    assert engine.running == 0


def test_unknown_session_is_404(make_client):
    client = make_client(FakeEngine([]))
    assert client.get("/api/sessions/999").status_code == 404
    assert client.post("/api/sessions/999/stop").status_code == 404
