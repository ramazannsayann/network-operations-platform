"""Where an SSH session actually connects: the connection-target resolver.

Devices are addressed by their management IP (and port) everywhere: scope checks,
de-duplication, the database. Only the moment a session is opened asks the resolver which
socket address to connect to. In production the resolver is the identity. Integration tests
install one that maps each fake device's management IP to 127.0.0.1:<port>, so a whole
fake campus runs on the loopback address of any machine without extra interfaces.
"""

from collections.abc import Callable

# (management IP, port) -> (host, port) to connect to.
TargetResolver = Callable[[str, int], tuple[str, int]]


def identity(host: str, port: int) -> tuple[str, int]:
    return host, port


_resolver: TargetResolver = identity


def set_target_resolver(resolver: TargetResolver | None) -> None:
    """Install a resolver for every session opened from now on (None: the identity)."""
    global _resolver
    _resolver = resolver or identity


def resolve_target(host: str, port: int) -> tuple[str, int]:
    return _resolver(host, port)
