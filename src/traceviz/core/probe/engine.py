import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Literal, Protocol

from traceviz.core.probe.events import HopEvent
from traceviz.core.probe.parser import parse_line

ProbeProtocol = Literal["icmp", "udp", "tcp"]

# Non-interactive mtr stops after 10 cycles without -c, so "unlimited" is the max count.
_UNLIMITED_CYCLES = 1_000_000_000  # mtr rejects values >= INT_MAX
_PROTOCOL_FLAGS: dict[str, list[str]] = {"icmp": [], "udp": ["-u"], "tcp": ["-T", "-P", "443"]}
_PERMISSION_MARKERS = ("Permission denied", "Failure to open", "Operation not permitted")
_PERMISSION_HINT = (
    "mtr could not open raw sockets. In Docker run with --cap-add NET_RAW; "
    "on a Linux host run: sudo setcap cap_net_raw+ep $(command -v mtr-packet)"
)


class ProbeError(RuntimeError):
    """The probe engine could not run or exited abnormally."""


class ProbeEngine(Protocol):
    def run(
        self, ip: str, protocol: ProbeProtocol = "icmp", max_hops: int = 30, cycles: int | None = 10
    ) -> AsyncIterator[HopEvent]: ...

    async def self_check(self) -> None: ...


def _explain(stderr: str) -> str:
    if any(m in stderr for m in _PERMISSION_MARKERS):
        return f"{stderr}\n{_PERMISSION_HINT}"
    return stderr


_STDERR_KEEP = 64 * 1024


async def _drain(stream: asyncio.StreamReader) -> bytes:
    """Read a pipe to EOF, keeping only the tail.

    stderr must be drained while stdout is being read: asyncio stops reading a pipe whose
    buffer is full, which blocks the child and, after a kill, keeps proc.wait() from returning.
    """
    tail = bytearray()
    while chunk := await stream.read(4096):
        tail += chunk
        del tail[:-_STDERR_KEEP]
    return bytes(tail)


class MtrEngine:
    def __init__(self, command: Sequence[str] = ("mtr",)) -> None:
        self.command = list(command)
        self.running = 0

    def build_argv(
        self, ip: str, protocol: ProbeProtocol, max_hops: int, cycles: int | None
    ) -> list[str]:
        argv = [*self.command, "--raw", "-m", str(max_hops)]
        argv += ["-c", str(_UNLIMITED_CYCLES if cycles is None else cycles)]
        argv += _PROTOCOL_FLAGS[protocol]
        return [*argv, "--", ip]

    async def run(
        self, ip: str, protocol: ProbeProtocol = "icmp", max_hops: int = 30, cycles: int | None = 10
    ) -> AsyncIterator[HopEvent]:
        argv = self.build_argv(ip, protocol, max_hops, cycles)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError as e:
            raise ProbeError(f"{argv[0]} not found — install mtr (package mtr-tiny)") from e
        except OSError as e:
            raise ProbeError(f"could not start {argv[0]}: {e.strerror or e}") from e
        self.running += 1
        got_event = False
        assert proc.stdout is not None and proc.stderr is not None
        stderr_task = asyncio.create_task(_drain(proc.stderr))
        try:
            async for raw in proc.stdout:
                event = parse_line(raw.decode(errors="replace"))
                if event is not None:
                    got_event = True
                    yield event
            returncode = await proc.wait()
            stderr = (await stderr_task).decode(errors="replace").strip()
            if returncode != 0 or not got_event:
                raise ProbeError(_explain(stderr or (
                    f"mtr exited with code {returncode}" if returncode else "mtr produced no output"
                )))
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            if not stderr_task.done():
                stderr_task.cancel()
            await asyncio.wait({stderr_task})
            self.running -= 1

    async def self_check(self) -> None:
        async for _ in self.run("127.0.0.1", max_hops=1, cycles=1):
            pass
