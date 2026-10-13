import asyncio
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from traceviz.core.geo.download import ATTRIBUTION
from traceviz.core.probe.engine import ProbeError
from traceviz.core.probe.target import InvalidTarget, ResolvedTarget, resolve_target
from traceviz.core.sessions.manager import SessionManager, SessionNotFound, TooManySessions
from traceviz.web.serialize import session_message

log = logging.getLogger(__name__)


class StartRequest(BaseModel):
    target: str = Field(min_length=1, max_length=253)
    kind: Literal["trace", "monitor"] = "trace"
    protocol: Literal["icmp", "udp", "tcp"] = "icmp"
    max_hops: int = Field(30, ge=1, le=64)
    cycles: int = Field(10, ge=1, le=100)


def create_app(
    manager: SessionManager,
    *,
    geo_available: bool,
    static_dir: Path | None = None,
    resolve: Callable[[str], ResolvedTarget] = resolve_target,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            await manager.engine.self_check()
        except ProbeError as e:
            app.state.probe_error = str(e)
            log.warning("probe self-check failed: %s", e)
        yield
        await manager.close()

    app = FastAPI(title="traceviz", lifespan=lifespan)
    app.state.probe_error = None

    @app.get("/api/health")
    def health() -> dict:
        return {
            "probe_ok": app.state.probe_error is None,
            "probe_error": app.state.probe_error,
            "geo_available": geo_available,
            "attribution": ATTRIBUTION,
        }

    @app.post("/api/sessions", status_code=201)
    async def start_session(req: StartRequest) -> dict:
        try:
            target = await asyncio.to_thread(resolve, req.target)
        except InvalidTarget as e:
            raise HTTPException(422, str(e)) from e
        try:
            sid = await manager.start(
                target, kind=req.kind, protocol=req.protocol, max_hops=req.max_hops, cycles=req.cycles
            )
        except TooManySessions as e:
            raise HTTPException(429, str(e)) from e
        return {"id": sid, "target": target.target, "target_ip": target.ip}

    @app.get("/api/sessions/{sid}")
    def get_session(sid: int) -> dict:
        try:
            return session_message(sid, manager.snapshot(sid))
        except SessionNotFound as e:
            raise HTTPException(404, "no such session") from e

    @app.post("/api/sessions/{sid}/stop", status_code=204)
    async def stop_session(sid: int) -> None:
        try:
            await manager.stop(sid)
        except SessionNotFound as e:
            raise HTTPException(404, "no such session") from e

    return app
