import asyncio
import contextlib
import logging
from collections.abc import Callable
from contextlib import aclosing, asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from traceviz.core.geo.download import ATTRIBUTION
from traceviz.core.probe.engine import ProbeError
from traceviz.core.probe.target import InvalidTarget, ResolvedTarget, resolve_target
from traceviz.core.sessions.manager import SessionManager, SessionNotFound, TooManySessions
from traceviz.web.serialize import session_message

log = logging.getLogger(__name__)


class UIFiles(StaticFiles):
    """Static UI files; HTML is revalidated so a rebuilt UI is picked up immediately.

    Hashed assets under /assets keep default caching.
    """

    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        if str(full_path).endswith(".html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


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

    @app.websocket("/ws/sessions/{sid}")
    async def session_stream(ws: WebSocket, sid: int) -> None:
        await ws.accept()
        try:
            manager.snapshot(sid)
        except SessionNotFound:
            await ws.close(code=4404)
            return

        async def pump() -> None:
            async with aclosing(manager.subscribe(sid)) as states:
                async for state in states:
                    await ws.send_json(session_message(sid, state))

        async def until_disconnect() -> None:
            while (await ws.receive())["type"] != "websocket.disconnect":
                pass

        pump_task = asyncio.create_task(pump())
        watch_task = asyncio.create_task(until_disconnect())
        done, pending = await asyncio.wait({pump_task, watch_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()  # cancelling pump closes the subscription -> may stop the session
        if pending:
            # asyncio.wait, not gather: if this handler is itself cancelled meanwhile, only its
            # own cancellation propagates (gather would re-raise the child's, which the server's
            # cancel scope doesn't recognise as its own).
            await asyncio.wait(pending)
        if pump_task in done and not pump_task.cancelled():
            error = pump_task.exception()
            if error is not None and not isinstance(error, (WebSocketDisconnect, RuntimeError)):
                log.error("session stream %s failed", sid, exc_info=error)
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await ws.close()

    if static_dir is not None and (static_dir / "index.html").is_file():
        app.mount("/", UIFiles(directory=static_dir, html=True), name="ui")

    return app
