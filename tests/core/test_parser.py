from collections import Counter
from pathlib import Path

import pytest

from traceviz.core.probe.events import HopEvent
from traceviz.core.probe.parser import parse_line

FIXTURE = Path(__file__).parents[1] / "fixtures" / "mtr_raw_cloudflare.txt"


def test_sent_record():
    assert parse_line("x 3 33003\n") == HopEvent("sent", 3)


def test_host_record():
    assert parse_line("h 0 10.100.0.1") == HopEvent("host", 0, ip="10.100.0.1")


def test_reply_record_converts_microseconds_to_ms():
    assert parse_line("p 2 550805 33002") == HopEvent("reply", 2, rtt_ms=550.805)


def test_dns_record():
    assert parse_line("d 9 one.one.one.one") == HopEvent("dns", 9, hostname="one.one.one.one")


@pytest.mark.parametrize(
    "line", ["", "\n", "m 3 1234", "x", "x abc 1", "p 1 notanumber 2", "garbage line here"]
)
def test_unknown_or_malformed_lines_are_ignored(line):
    assert parse_line(line) is None


def test_parses_real_fixture():
    events = [parse_line(line) for line in FIXTURE.read_text().splitlines()]
    kinds = Counter(e.kind for e in events if e is not None)
    assert kinds == {"sent": 33, "host": 26, "reply": 27, "dns": 13}
