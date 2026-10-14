import asyncio
import contextlib
import logging
from collections.abc import Callable, Sequence
from contextlib import aclosing, asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from traceviz.core.geo.download import ATTRIBUTION
from traceviz.core.probe.engine import ProbeError
from traceviz.core.probe.target import InvalidTarget, ResolvedTarget, resolve_target
from traceviz.core.sessions.manager import SessionManager, SessionNotFound, TooManySessions
from traceviz.web.serialize import session_message

log = logging.getLogger(__name__)


LOCAL_HOSTS = ("localhost", "127.0.0.1")
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class OriginGuard:
    """Refuse cross-site requests to the local API.

    Browsers send `Origin` on cross-site requests; a page on another site must not be able to
    start or stop probes (POST) or read session streams (WebSocket). Requests are allowed when
    the origin's host matches the request's own Host, or is one of `allowed_hosts` (e.g. the
    Vite dev server on localhost:5173).
    """

    def __init__(self, app, allowed_hosts: Sequence[str]) -> None:
        self.app = app
        self.allowed_hosts = set(allowed_hosts)

    def _allowed(self, origin: str, host_header: str) -> bool:
        origin_host = urlsplit(origin).hostname
        if origin_host is None:  # includes the opaque origin "null"
            return False
        return origin_host == host_header.split(":")[0] or origin_host in self.allowed_hosts

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope["headers"])
            origin = headers.get(b"origin")
            host = headers.get(b"host", b"").decode("latin-1")
            if origin is not None and not self._allowed(origin.decode("latin-1"), host):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 4403})
                    return
                if scope["method"] not in _SAFE_METHODS:
                    response = JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def _task_error(task: asyncio.Task) -> BaseException | None:
    """The exception a finished task raised, if any (None if still running or cancelled)."""
    return task.exception() if task.done() and not task.cancelled() else None


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
    allowed_hosts: Sequence[str] = LOCAL_HOSTS,
) -> FastAPI:
    """`allowed_hosts` are the Host names the server answers to (DNS-rebinding defence);
    pass ("*",) only when deliberately serving on a network interface."""
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
    app.add_middleware(OriginGuard, allowed_hosts=allowed_hosts)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))
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
        if (receive_error := _task_error(watch_task)) is not None:
            log.debug("session stream %s: receive failed", sid, exc_info=receive_error)
        if pump_task in done and not pump_task.cancelled():
            error = _task_error(pump_task)
            if error is not None and not isinstance(error, (WebSocketDisconnect, RuntimeError)):
                log.error("session stream %s failed", sid, exc_info=error)
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await ws.close()

    if static_dir is not None and (static_dir / "index.html").is_file():
        app.mount("/", UIFiles(directory=static_dir, html=True), name="ui")

    return app
