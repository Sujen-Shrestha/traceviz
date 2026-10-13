import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Literal, Protocol

from traceviz.core.probe.events import HopEvent
from traceviz.core.probe.parser import parse_line

ProbeProtocol = Literal["icmp", "udp", "tcp"]

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


class MtrEngine:
    def __init__(self, command: Sequence[str] = ("mtr",)) -> None:
        self.command = list(command)
        self.running = 0

    def build_argv(
        self, ip: str, protocol: ProbeProtocol, max_hops: int, cycles: int | None
    ) -> list[str]:
        argv = [*self.command, "--raw", "-m", str(max_hops)]
        if cycles is not None:
            argv += ["-c", str(cycles)]
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
        self.running += 1
        got_event = False
        try:
            assert proc.stdout is not None and proc.stderr is not None
            async for raw in proc.stdout:
                event = parse_line(raw.decode(errors="replace"))
                if event is not None:
                    got_event = True
                    yield event
            returncode = await proc.wait()
            stderr = (await proc.stderr.read()).decode(errors="replace").strip()
            if returncode != 0 or (stderr and not got_event):
                raise ProbeError(_explain(stderr or f"mtr exited with code {returncode}"))
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            self.running -= 1

    async def self_check(self) -> None:
        async for _ in self.run("127.0.0.1", max_hops=1, cycles=1):
            pass
