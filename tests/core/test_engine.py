import asyncio
import sys
from pathlib import Path

import pytest

from traceviz.core.probe.engine import MtrEngine, ProbeError
from traceviz.core.probe.events import HopEvent

FIXTURES = Path(__file__).parents[1] / "fixtures"
FAKE = str(FIXTURES / "fake_mtr.py")
DATA = str(FIXTURES / "mtr_raw_cloudflare.txt")


def fake_engine(mode: str) -> MtrEngine:
    return MtrEngine(command=(sys.executable, FAKE, mode, DATA))


def test_argv_icmp_with_cycles():
    argv = MtrEngine().build_argv("1.1.1.1", "icmp", 30, 10)
    assert argv == ["mtr", "--raw", "-m", "30", "-c", "10", "--", "1.1.1.1"]


def test_argv_unlimited_cycles_passes_max_count():
    # Non-interactive mtr defaults to 10 cycles when -c is omitted, so "unlimited" must be explicit.
    argv = MtrEngine().build_argv("1.1.1.1", "udp", 20, None)
    assert argv == ["mtr", "--raw", "-m", "20", "-c", "1000000000", "-u", "--", "1.1.1.1"]


def test_argv_tcp_uses_port_443():
    argv = MtrEngine().build_argv("2606:4700::1111", "tcp", 30, 5)
    assert argv == ["mtr", "--raw", "-m", "30", "-c", "5", "-T", "-P", "443", "--", "2606:4700::1111"]


def test_argv_target_always_after_double_dash():
    argv = MtrEngine().build_argv("--help", "icmp", 30, 1)
    assert argv[-2:] == ["--", "--help"]


async def test_replays_events():
    events = [e async for e in fake_engine("replay").run("1.1.1.1")]
    assert len(events) == 99
    assert events[0] == HopEvent("sent", 0)


async def test_nonzero_exit_raises_with_permission_hint():
    with pytest.raises(ProbeError, match="NET_RAW"):
        async for _ in fake_engine("fail").run("1.1.1.1"):
            pass


async def test_stderr_without_events_is_an_error_even_on_exit_zero():
    with pytest.raises(ProbeError, match="Failed to resolve"):
        async for _ in fake_engine("stderr-only").run("1.1.1.1"):
            pass


async def test_closing_early_kills_the_process():
    engine = fake_engine("hang")
    gen = engine.run("1.1.1.1", cycles=None)
    seen = [await anext(gen) for _ in range(5)]
    assert len(seen) == 5 and engine.running == 1
    await gen.aclose()
    assert engine.running == 0


async def test_missing_binary_is_probe_error():
    with pytest.raises(ProbeError, match="not found"):
        async for _ in MtrEngine(command=("definitely-not-mtr-xyz",)).run("1.1.1.1"):
            pass


async def test_self_check_reports_failure():
    with pytest.raises(ProbeError, match="NET_RAW"):
        await fake_engine("fail").self_check()


async def test_self_check_passes():
    await fake_engine("replay").self_check()


async def test_unexecutable_command_is_probe_error(tmp_path):
    not_executable = tmp_path / "mtr"
    not_executable.write_text("")
    with pytest.raises(ProbeError, match="could not start"):
        async for _ in MtrEngine(command=(str(not_executable),)).run("1.1.1.1"):
            pass


async def test_exit_zero_with_no_output_is_an_error():
    with pytest.raises(ProbeError, match="no output"):
        async for _ in fake_engine("silent").run("1.1.1.1"):
            pass


async def test_lots_of_stderr_does_not_deadlock():
    async def collect():
        return [e async for e in fake_engine("noisy").run("1.1.1.1")]

    events = await asyncio.wait_for(collect(), 10)
    assert len(events) == 99


async def test_mtr_runs_in_its_own_process_group(tmp_path):
    # Ctrl-C in the terminal must reach only traceviz, which then stops mtr cleanly;
    # if it also hit mtr, the session would end as "failed" instead of "stopped".
    import os

    out = tmp_path / "pgid"
    with pytest.raises(ProbeError):  # the fake prints nothing
        async for _ in MtrEngine(command=(sys.executable, FAKE, "pgid", str(out))).run("1.1.1.1"):
            pass
    assert int(out.read_text()) != os.getpgrp()


def test_engine_works_under_uvloop():
    # `traceviz serve` runs on uvloop (uvicorn[standard]), whose subprocess API is narrower.
    import uvloop

    uvloop.run(fake_engine("replay").self_check())
