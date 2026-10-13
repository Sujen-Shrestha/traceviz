import asyncio
from pathlib import Path

from traceviz.core.probe.events import HopEvent
from traceviz.core.probe.parser import parse_line

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_events() -> list[HopEvent]:
    lines = (FIXTURES / "mtr_raw_cloudflare.txt").read_text().splitlines()
    return [e for e in map(parse_line, lines) if e is not None]


class DictReader:
    """In-memory stand-in for a maxminddb Reader."""

    def __init__(self, data: dict[str, dict]):
        self.data = data

    def get(self, ip: str) -> dict | None:
        return self.data.get(ip)


CITY_FIXTURE = {
    "1.1.1.1": {
        "city": {"names": {"en": "Sydney"}},
        "country": {"iso_code": "AU", "names": {"en": "Australia"}},
        "location": {"latitude": -33.8688, "longitude": 151.209},
    },
}


class FakeEngine:
    """Scripted ProbeEngine for tests."""

    def __init__(self, events, *, delay=0.0, error=None, hang=False, check_error=None):
        self.events = list(events)
        self.delay = delay
        self.error = error
        self.hang = hang
        self.check_error = check_error
        self.calls: list[tuple] = []
        self.running = 0

    async def run(self, ip, protocol="icmp", max_hops=30, cycles=10):
        self.calls.append((ip, protocol, max_hops, cycles))
        self.running += 1
        try:
            for event in self.events:
                if self.delay:
                    await asyncio.sleep(self.delay)
                yield event
            if self.error:
                raise self.error
            if self.hang:
                await asyncio.Event().wait()
        finally:
            self.running -= 1

    async def self_check(self):
        if self.check_error:
            raise self.check_error
