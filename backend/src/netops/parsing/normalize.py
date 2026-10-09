"""Turning raw CLI field values into canonical values."""

import ipaddress
import re

from netops.db.enums import Duplex

_HEX12 = re.compile(r"^[0-9a-f]{12}$")
_SPEED = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[kmg])", re.IGNORECASE)
_UNIT_MBPS = {"k": 0.001, "m": 1, "g": 1000}
_MAX_VLAN = 4094


def mac(value: str | None) -> str | None:
    """'0011.2233.4455', '00:11:22:33:44:55' or '00-11-...' -> '00:11:22:33:44:55'."""
    if not value:
        return None
    digits = re.sub(r"[.:\-\s]", "", value).lower()
    if not _HEX12.match(digits):
        return None
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def ip(value: str | None) -> str | None:
    """Canonical host address, or None for '', 'unassigned', 'unknown', ..."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def ip_with_prefix(address: str | None, prefix_length: str | None) -> str | None:
    """'10.0.20.2', '24' -> '10.0.20.2/24'."""
    host = ip(address)
    if host is None or not prefix_length:
        return None
    try:
        return str(ipaddress.ip_interface(f"{host}/{int(prefix_length)}"))
    except ValueError:
        return None


def network(address: str, prefix_length: str | None) -> str | None:
    """'10.0.20.0', '24' -> '10.0.20.0/24' (host bits cleared)."""
    if not address or not prefix_length:
        return None
    try:
        return str(ipaddress.ip_network(f"{address}/{int(prefix_length)}", strict=False))
    except ValueError:
        return None


def integer(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    return int(value) if value.isdigit() else None


def vlan_list(values: str | list[str] | None) -> tuple[int, ...] | None:
    """Expand IOS VLAN lists: 'ALL' -> 1..4094, 'NONE' -> (), '1-3,10' -> (1, 2, 3, 10).

    ntc-templates may already have split the list into pieces (one per comma or line).
    """
    if values is None:
        return None
    text = ",".join(values) if isinstance(values, list) else values
    text = text.replace(" ", "").strip(",")
    if not text:
        return None
    if text.upper() == "ALL":
        return tuple(range(1, _MAX_VLAN + 1))
    if text.upper() == "NONE":
        return ()
    vlans: set[int] = set()
    for part in text.split(","):
        if not part:
            continue
        low, _, high = part.partition("-")
        if not low.isdigit() or (high and not high.isdigit()):
            raise ValueError(f"not a VLAN list: {text!r}")
        vlans.update(range(int(low), int(high or low) + 1))
    return tuple(sorted(v for v in vlans if 1 <= v <= _MAX_VLAN))


def speed_mbps(value: str | None) -> int | None:
    """'1000Mb/s', '10Gb/s', 'a-100', '100Mbps' -> Mb/s; None for 'Auto-speed' and the like."""
    if not value:
        return None
    if value.isdigit():
        return int(value)
    match = _SPEED.search(value)
    if match is None:
        tail = value.rsplit("-", 1)[-1]
        return int(tail) if tail.isdigit() else None
    return int(float(match["value"]) * _UNIT_MBPS[match["unit"].lower()])


def duplex(value: str | None) -> Duplex | None:
    if not value:
        return None
    text = value.lower()
    if "full" in text:
        return Duplex.FULL
    if "half" in text:
        return Duplex.HALF
    if "auto" in text:
        return Duplex.AUTO
    return Duplex.UNKNOWN
