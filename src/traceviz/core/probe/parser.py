"""Parser for `mtr --raw` output.

Record formats (mtr 0.93+):
  x <pos> <seq>          probe sent
  h <pos> <ip>           host seen at position
  p <pos> <rtt_us> <seq> reply received, RTT in microseconds
  d <pos> <hostname>     reverse DNS result
Other records (e.g. `m` for MPLS) are ignored.
"""

from traceviz.core.probe.events import HopEvent


def parse_line(line: str) -> HopEvent | None:
    parts = line.split()
    if len(parts) < 3:
        return None
    tag = parts[0]
    try:
        index = int(parts[1])
    except ValueError:
        return None
    match tag:
        case "x":
            return HopEvent("sent", index)
        case "h":
            return HopEvent("host", index, ip=parts[2])
        case "p":
            try:
                rtt_us = int(parts[2])
            except ValueError:
                return None
            return HopEvent("reply", index, rtt_ms=rtt_us / 1000)
        case "d":
            return HopEvent("dns", index, hostname=parts[2])
    return None
