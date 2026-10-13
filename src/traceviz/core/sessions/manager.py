import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import UTC, datetime

from traceviz.core.geo.lookup import GeoLookup
from traceviz.core.probe.engine import ProbeEngine, ProbeError, ProbeProtocol
from traceviz.core.probe.target import ResolvedTarget
from traceviz.core.sessions.state import SessionKind, TraceState
from traceviz.core.store.models import MonitorSampleRecord
from traceviz.core.store.repo import TraceRepository


class TooManySessions(RuntimeError):
    """The concurrent session limit has been reached."""


class SessionNotFound(KeyError):
    """No session with that id exists in this manager."""


@dataclass
class _Session:
    id: int
    state: TraceState
    task: asyncio.Task | None = None
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    # hop index -> (sent, received, sum_ms) at the last monitor flush
    flushed: dict[int, tuple[int, int, float]] = field(default_factory=dict)


class SessionManager:
    def __init__(
        self,
        engine: ProbeEngine,
        geo: GeoLookup,
        repo: TraceRepository,
        *,
        max_sessions: int = 3,
        trace_timeout_s: float = 300.0,
        sample_interval_s: float = 10.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.engine = engine
        self.geo = geo
        self.repo = repo
        self.max_sessions = max_sessions
        self.trace_timeout_s = trace_timeout_s
        self.sample_interval_s = sample_interval_s
        self.clock = clock
        self._sessions: dict[int, _Session] = {}

    def _get(self, session_id: int) -> _Session:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise SessionNotFound(session_id) from None

    async def start(
        self,
        target: ResolvedTarget,
        *,
        kind: SessionKind = "trace",
        protocol: ProbeProtocol = "icmp",
        max_hops: int = 30,
        cycles: int = 10,
    ) -> int:
        active = sum(1 for s in self._sessions.values() if not s.done.is_set())
        if active >= self.max_sessions:
            raise TooManySessions(f"at most {self.max_sessions} sessions can run at once")
        state = TraceState(target=target.target, target_ip=target.ip, protocol=protocol, kind=kind)
        session = _Session(self.repo.create_trace(state, self.clock()), state)
        self._sessions[session.id] = session
        session.task = asyncio.create_task(
            self._run(session, max_hops, None if kind == "monitor" else cycles)
        )
        return session.id

    async def _run(self, s: _Session, max_hops: int, cycles: int | None) -> None:
        state = s.state
        timeout = self.trace_timeout_s if state.kind == "trace" else None
        sampler = asyncio.create_task(self._sample_loop(s)) if state.kind == "monitor" else None
        try:
            async with asyncio.timeout(timeout):
                events = self.engine.run(state.target_ip, state.protocol, max_hops, cycles)
                async with aclosing(events):
                    async for event in events:
                        hop = state.apply(event)
                        if hop.ip and hop.geo is None:
                            hop.geo = self.geo.lookup(hop.ip)
                        self._publish(s)
            state.status = "completed"
        except asyncio.CancelledError:
            state.status = "stopped"
        except TimeoutError:
            state.status = "failed"
            state.error = f"timed out after {timeout:.0f}s"
        except ProbeError as e:
            state.status = "failed"
            state.error = str(e)
        finally:
            if sampler:
                sampler.cancel()
                await asyncio.gather(sampler, return_exceptions=True)
            self._finish(s)

    def _finish(self, s: _Session) -> None:
        if s.state.kind == "monitor":
            self._flush_samples(s)
        self.repo.finish_trace(s.id, s.state, self.clock())
        s.done.set()
        self._publish(s)

    async def _sample_loop(self, s: _Session) -> None:
        while True:
            await asyncio.sleep(self.sample_interval_s)
            self._flush_samples(s)

    def _flush_samples(self, s: _Session) -> None:
        now = self.clock()
        rows = []
        for hop in s.state.hops:
            prev_sent, prev_received, prev_sum = s.flushed.get(hop.index, (0, 0, 0.0))
            d_sent = hop.sent - prev_sent
            d_received = hop.received - prev_received
            if d_sent <= 0 and d_received <= 0:
                continue
            avg = (hop.sum_ms - prev_sum) / d_received if d_received else None
            rows.append(
                MonitorSampleRecord(
                    trace_id=s.id, ts=now, hop_index=hop.index,
                    sent=d_sent, received=d_received, avg_ms=avg,
                )
            )
            s.flushed[hop.index] = (hop.sent, hop.received, hop.sum_ms)
        if rows:
            self.repo.add_monitor_samples(rows)

    def _publish(self, s: _Session) -> None:
        snap = s.state.snapshot()
        for queue in s.subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(snap)

    async def subscribe(self, session_id: int) -> AsyncIterator[TraceState]:
        s = self._get(session_id)
        queue: asyncio.Queue[TraceState] = asyncio.Queue(maxsize=1)
        queue.put_nowait(s.state.snapshot())
        s.subscribers.add(queue)
        try:
            while True:
                snap = await queue.get()
                yield snap
                if snap.status != "running":
                    return
        finally:
            s.subscribers.discard(queue)
            if not s.subscribers and not s.done.is_set():
                await self.stop(session_id)

    async def stop(self, session_id: int) -> None:
        s = self._get(session_id)
        if s.task and not s.task.done():
            s.task.cancel()
            await asyncio.gather(s.task, return_exceptions=True)
        if not s.done.is_set():
            # Cancelled before _run's first step, so its handlers never ran.
            s.state.status = "stopped"
            self._finish(s)

    async def wait(self, session_id: int) -> TraceState:
        s = self._get(session_id)
        await s.done.wait()
        return s.state.snapshot()

    async def close(self) -> None:
        for session_id in list(self._sessions):
            await self.stop(session_id)
