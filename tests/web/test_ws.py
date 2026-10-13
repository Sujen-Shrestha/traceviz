import pytest
from starlette.websockets import WebSocketDisconnect

from tests.fakes import FakeEngine, fixture_events
from tests.web.conftest import wait_for_status


def start(client, **body):
    return client.post("/api/sessions", json={"target": "one.one.one.one", **body}).json()["id"]


def test_streams_until_final_message_then_closes(make_client):
    client = make_client(FakeEngine(fixture_events(), delay=0.002))
    sid = start(client)
    with client.websocket_connect(f"ws://127.0.0.1:8080/ws/sessions/{sid}") as ws:
        messages = []
        while True:
            msg = ws.receive_json()
            messages.append(msg)
            if msg["status"] != "running":
                break
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert all(m["type"] == "state" and m["id"] == sid for m in messages)
    assert messages[-1]["status"] == "completed"
    assert messages[-1]["summary"]["reached"] is True
    assert len(messages[-1]["hops"]) == 9


def test_unknown_session_closes_with_4404(make_client):
    client = make_client(FakeEngine([]))
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("ws://127.0.0.1:8080/ws/sessions/999") as ws:
            ws.receive_json()
    assert exc.value.code == 4404


def test_closing_the_last_socket_stops_the_monitor(make_client):
    engine = FakeEngine(fixture_events()[:5], hang=True)
    client = make_client(engine)
    sid = start(client, kind="monitor")
    with client.websocket_connect(f"ws://127.0.0.1:8080/ws/sessions/{sid}") as ws:
        assert ws.receive_json()["status"] == "running"
    wait_for_status(client, sid, {"stopped"})
    assert engine.running == 0


def test_session_survives_while_another_socket_is_open(make_client):
    engine = FakeEngine(fixture_events()[:5], hang=True)
    client = make_client(engine)
    sid = start(client, kind="monitor")
    with client.websocket_connect(f"ws://127.0.0.1:8080/ws/sessions/{sid}") as first:
        first.receive_json()
        with client.websocket_connect(f"ws://127.0.0.1:8080/ws/sessions/{sid}") as second:
            second.receive_json()
        assert client.get(f"/api/sessions/{sid}").json()["status"] == "running"
    wait_for_status(client, sid, {"stopped"})


def test_cross_origin_websocket_is_refused(make_client):
    client = make_client(FakeEngine(fixture_events()))
    sid = start(client)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"ws://127.0.0.1:8080/ws/sessions/{sid}", headers={"Origin": "https://evil.example"}) as ws:
            ws.receive_json()
    assert exc.value.code == 4403
