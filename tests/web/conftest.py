import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.fakes import CITY_FIXTURE, DictReader
from traceviz.core.geo.lookup import GeoLookup
from traceviz.core.probe.target import ResolvedTarget
from traceviz.core.sessions.manager import SessionManager
from traceviz.core.store.repo import TraceRepository, init_db
from traceviz.web.app import create_app


def fixed_resolver(target: str) -> ResolvedTarget:
    return ResolvedTarget(target, "1.1.1.1")


@pytest.fixture
def make_client(tmp_path) -> Iterator:
    clients: list[TestClient] = []

    def build(engine, *, static_dir=None, resolve=None, max_sessions=3) -> TestClient:
        repo = TraceRepository(init_db(tmp_path / f"t{len(clients)}.db"))
        manager = SessionManager(
            engine, GeoLookup(city=DictReader(CITY_FIXTURE), asn=None), repo, max_sessions=max_sessions
        )
        app = create_app(manager, geo_available=True, static_dir=static_dir, resolve=resolve or fixed_resolver)
        client = TestClient(app)
        client.__enter__()  # run lifespan (startup self-check)
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)


def wait_for_status(client: TestClient, sid: int, statuses: set[str], timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    body: dict = {}
    while time.monotonic() < deadline:
        body = client.get(f"/api/sessions/{sid}").json()
        if body["status"] in statuses:
            return body
        time.sleep(0.02)
    raise AssertionError(f"session {sid} still {body.get('status')}")
