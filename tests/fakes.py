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
