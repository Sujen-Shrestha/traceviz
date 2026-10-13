import socket

import pytest

from traceviz.core.probe.target import InvalidTarget, ResolvedTarget, resolve_target


def fake_resolver(addrs):
    def resolver(host, port, proto=0):
        if not addrs:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, proto, "", (a, 0))
            for a in addrs
        ]

    return resolver


def test_ipv4_literal_needs_no_dns():
    assert resolve_target("1.1.1.1", resolver=fake_resolver([])) == ResolvedTarget("1.1.1.1", "1.1.1.1")


def test_ipv6_literal():
    assert resolve_target("2606:4700::1111", resolver=fake_resolver([])).ip == "2606:4700::1111"


def test_hostname_prefers_ipv4():
    r = resolve_target(" example.com ", resolver=fake_resolver(["2606:2800::1", "93.184.215.14"]))
    assert r == ResolvedTarget("example.com", "93.184.215.14")


def test_hostname_with_only_ipv6():
    assert resolve_target("v6.example", resolver=fake_resolver(["2001:db8::5"])).ip == "2001:db8::5"


@pytest.mark.parametrize(
    "bad", ["", "   ", "--help", "-c 1", "a;rm -rf /", "-x.com", "exa mple.com", "a" * 64 + ".com", "$(id)"]
)
def test_rejects_invalid_targets(bad):
    with pytest.raises(InvalidTarget):
        resolve_target(bad, resolver=fake_resolver(["1.2.3.4"]))


def test_unresolvable_hostname():
    with pytest.raises(InvalidTarget, match="could not resolve"):
        resolve_target("nonexistent.invalid", resolver=fake_resolver([]))
