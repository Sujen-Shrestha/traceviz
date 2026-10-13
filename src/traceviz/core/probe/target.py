import ipaddress
import re
import socket
from dataclasses import dataclass

_LABEL = r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
_HOSTNAME = re.compile(rf"^(?=.{{1,253}}$){_LABEL}(\.{_LABEL})*\.?$")


class InvalidTarget(ValueError):
    """The target is not a valid hostname/IP or cannot be resolved."""


@dataclass(frozen=True)
class ResolvedTarget:
    target: str
    ip: str


def resolve_target(target: str, resolver=socket.getaddrinfo) -> ResolvedTarget:
    t = target.strip()
    try:
        return ResolvedTarget(t, str(ipaddress.ip_address(t)))
    except ValueError:
        pass
    if not _HOSTNAME.match(t):
        raise InvalidTarget(f"not a valid hostname or IP address: {target!r}")
    try:
        infos = resolver(t, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise InvalidTarget(f"could not resolve {t}: {e.strerror}") from e
    addrs = [info[4][0] for info in infos]
    if not addrs:
        raise InvalidTarget(f"could not resolve {t}: no addresses")
    v4 = [a for a in addrs if ":" not in a]
    return ResolvedTarget(t, (v4 or addrs)[0])
