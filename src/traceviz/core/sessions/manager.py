import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import UTC, datetime

from traceviz.core.geo.lookup import GeoLookup
from traceviz.core.probe.engine import ProbeEngine, ProbeError, ProbeInterrupted, ProbeProtocol
from traceviz.core.probe.target import ResolvedTarget
from traceviz.core.sessions.state import SessionKind, TraceState
from traceviz.core.store.models import MonitorSampleRecord
from traceviz.core.store.repo import TraceRepository

log = logging.getLogger(__name__)


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
    finishing: bool = False  # the final save has started; later stoppers just wait for it
    watched: bool = False  # at least one subscriber has connected
    # hop index -> (sent, received, sum_ms) at the last successful monitor flush
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
        subscriber_grace_s: float = 15.0,
        max_finished: int = 50,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.engine = engine
        self.geo = geo
        self.repo = repo
        self.max_sessions = max_sessions
        self.trace_timeout_s = trace_timeout_s
        self.sample_interval_s = sample_interval_s
        self.subscriber_grace_s = subscriber_grace_s
        self.max_finished = max_finished
        self.clock = clock
        self._sessions: dict[int, _Session] = {}
        self._starting = 0
        self._background: set[asyncio.Task] = set()
        self._watchdogs: set[asyncio.Task] = set()

    def _get(self, session_id: int) -> _Session:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise SessionNotFound(session_id) from None

    def snapshot(self, session_id: int) -> TraceState:
        return self._get(session_id).state.snapshot()

    async def start(
        self,
        target: ResolvedTarget,
        *,
        kind: SessionKind = "trace",
        protocol: ProbeProtocol = "icmp",
        max_hops: int = 30,
        cycles: int = 10,
    ) -> int:
        active = sum(1 for s in self._sessions.values() if not s.done.is_set()) + self._starting
        if active >= self.max_sessions:
            raise TooManySessions(f"at most {self.max_sessions} sessions can run at once")
        state = TraceState(target=target.target, target_ip=target.ip, protocol=protocol, kind=kind)
        self._starting += 1  # reserve the slot across the await below
        try:
            session_id = await asyncio.to_thread(self.repo.create_trace, state, self.clock())
        finally:
            self._starting -= 1
        session = _Session(session_id, state)
        self._evict_finished()
        self._sessions[session.id] = session
        session.task = asyncio.create_task(
            self._run(session, max_hops, None if kind == "monitor" else cycles)
        )
        watchdog = asyncio.create_task(self._stop_if_unwatched(session))
        self._watchdogs.add(watchdog)
        watchdog.add_done_callback(self._watchdogs.discard)
        return session.id

    def _evict_finished(self) -> None:
        """Forget the oldest finished sessions beyond `max_finished` (they stay in the history DB)."""
        finished = sorted(
            sid for sid, s in self._sessions.items() if s.done.is_set() and not s.subscribers
        )
        for sid in finished[: max(0, len(finished) - self.max_finished)]:
            del self._sessions[sid]

    async def _stop_if_unwatched(self, s: _Session) -> None:
        # A session nobody ever subscribes to (tab closed between start and connect)
        # would otherwise run forever and hold a slot.
        await asyncio.sleep(self.subscriber_grace_s)
        if not s.watched and not s.done.is_set():
            log.info("stopping session %s: no subscriber within %ss", s.id, self.subscriber_grace_s)
            await self.stop(s.id)

    async def _run(self, s: _Session, max_hops: int, cycles: int | None) -> None:
        state = s.state
        timeout = self.trace_timeout_s if state.kind == "trace" else None
        stop_sampling = asyncio.Event()
        sampler = (
            asyncio.create_task(self._sample_loop(s, stop_sampling)) if state.kind == "monitor" else None
        )
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
        except (asyncio.CancelledError, ProbeInterrupted):
            state.status = "stopped"
        except TimeoutError:
            state.status = "failed"
            state.error = f"timed out after {timeout:.0f}s"
        except ProbeError as e:
            state.status = "failed"
            state.error = str(e)
        except Exception as e:
            state.status = "failed"
            state.error = f"{type(e).__name__}: {e}"
        finally:
            if sampler:
                # Let an in-flight sample write finish rather than cancelling it, so that
                # once the session is done all of its samples are saved.
                stop_sampling.set()
                await asyncio.wait({sampler})
            # Shielded: a second cancellation (e.g. a stopper being torn down) must not
            # interrupt saving the final state and releasing waiters.
            await asyncio.shield(self._finish(s))

    async def _finish(self, s: _Session) -> None:
        if s.finishing:
            await s.done.wait()
            return
        s.finishing = True
        if s.state.kind == "monitor":
            await self._save_samples(s)
        await asyncio.to_thread(self.repo.finish_trace, s.id, s.state.snapshot(), self.clock())
        s.done.set()
        self._publish(s)

    async def _sample_loop(self, s: _Session, stop: asyncio.Event) -> None:
        while True:
            try:
                await asyncio.wait_for(stop.wait(), self.sample_interval_s)
                return
            except TimeoutError:
                await self._save_samples(s)

    async def _save_samples(self, s: _Session) -> None:
        try:
            await self._flush_samples(s)
        except Exception:
            log.exception("could not save monitor samples for session %s", s.id)

    async def _flush_samples(self, s: _Session) -> None:
        now = self.clock()
        rows = []
        flushed = dict(s.flushed)
        for hop in s.state.hops:
            prev_sent, prev_received, prev_sum = flushed.get(hop.index, (0, 0, 0.0))
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
            flushed[hop.index] = (hop.sent, hop.received, hop.sum_ms)
        if not rows:
            return
        # Advance first: if we're cancelled mid-write the thread still completes the write,
        # so those deltas must count as saved. Roll back only when the write itself fails.
        previous, s.flushed = s.flushed, flushed
        try:
            await asyncio.to_thread(self.repo.add_monitor_samples, rows)
        except Exception:
            s.flushed = previous
            raise

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
        s.watched = True
        try:
            while True:
                snap = await queue.get()
                yield snap
                if snap.status != "running":
                    return
        finally:
            s.subscribers.discard(queue)
            if not s.subscribers and not s.done.is_set():
                # Don't await the stop here: subscribers (e.g. WebSocket handlers) are often
                # being torn down or cancelled, and stopping must complete regardless.
                task = asyncio.create_task(self.stop(session_id))
                self._background.add(task)
                task.add_done_callback(self._background.discard)

    async def stop(self, session_id: int) -> None:
        s = self._get(session_id)
        if s.task and not s.task.done():
            if not s.finishing:  # never interrupt a save that's already under way
                s.task.cancel()
            # asyncio.wait, unlike gather, doesn't forward our own cancellation into the task.
            await asyncio.wait({s.task})
        if not s.done.is_set():
            # Cancelled before _run's first step (or during its cleanup), so finish here.
            if s.state.status == "running":
                s.state.status = "stopped"
            await self._finish(s)

    async def wait(self, session_id: int) -> TraceState:
        s = self._get(session_id)
        await s.done.wait()
        return s.state.snapshot()

    async def close(self) -> None:
        for watchdog in list(self._watchdogs):
            watchdog.cancel()
        for session_id in list(self._sessions):
            await self.stop(session_id)
        if self._background:
            await asyncio.wait(set(self._background))
