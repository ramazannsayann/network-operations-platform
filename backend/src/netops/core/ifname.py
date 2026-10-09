"""Canonical Cisco interface names.

The same port appears under many spellings: "Gi1/0/1" in ``show ip interface brief`` and
CDP, "Gig 1/0/1" in LLDP, "GigabitEthernet1/0/1" in ``show interfaces``. ``normalize``
maps all of them to the long form IOS/IOS-XE uses in ``show interfaces``, so interfaces
can be matched across commands, protocols and devices (interfaces.name_normalized).

Names whose type is not recognised are returned unchanged apart from whitespace.
"""

import re
from typing import Final

from netops.db.enums import InterfaceKind

# Canonical type names as IOS/IOS-XE print them, with other full spellings seen in the wild.
_TYPES: Final[dict[str, tuple[str, ...]]] = {
    "Ethernet": (),
    "FastEthernet": (),
    "GigabitEthernet": ("GigE",),
    "TwoGigabitEthernet": ("TwoGigE",),
    "FiveGigabitEthernet": ("FiveGigE",),
    "TenGigabitEthernet": ("TenGigE",),
    "TwentyFiveGigE": ("TwentyFiveGigabitEthernet",),
    "FortyGigabitEthernet": ("FortyGigE",),
    "HundredGigE": ("HundredGigabitEthernet",),
    "AppGigabitEthernet": (),
    "Port-channel": (),
    "Vlan": (),
    "Loopback": (),
    "Tunnel": (),
    "Serial": (),
    "Null": (),
    "BDI": (),
    "Dialer": (),
    "Multilink": (),
    "Cellular": (),
    "Virtual-Access": (),
    "Virtual-Template": (),
}

# Abbreviations that are not unique prefixes of one type, pinned to what Cisco means.
_PINNED: Final[dict[str, str]] = {
    "tw": "TwoGigabitEthernet",  # also a prefix of TwentyFiveGigE
    "twe": "TwentyFiveGigE",
    "vi": "Virtual-Access",  # also a prefix of Virtual-Template
    "vt": "Virtual-Template",
}

# Shortest abbreviation accepted; single letters ("G1/0/1") are too ambiguous to trust.
_MIN_ABBREVIATION = 2

# Type (letters, hyphens), optional whitespace, then the number part starting with a digit:
# slots/ports, subinterface ".100", channel ":1".
_NAME_RE: Final = re.compile(r"(?P<type>[A-Za-z][A-Za-z-]*?)\s*(?P<number>\d\S*)")


def _key(text: str) -> str:
    """Comparison key: case- and hyphen-insensitive ("Port-Channel" == "portchannel")."""
    return text.replace("-", "").lower()


# Every full spelling's key -> canonical name.
_SPELLINGS: Final[dict[str, str]] = {
    _key(spelling): canonical
    for canonical, alternatives in _TYPES.items()
    for spelling in (canonical, *alternatives)
}


def _canonical_type(type_text: str) -> str | None:
    key = _key(type_text)
    if key in _PINNED:
        return _PINNED[key]
    if len(key) < _MIN_ABBREVIATION:
        return None
    matches = {canonical for spelling, canonical in _SPELLINGS.items() if spelling.startswith(key)}
    return matches.pop() if len(matches) == 1 else None


def normalize(name: str) -> str:
    """Return the canonical long form of a Cisco interface name.

    >>> normalize("Gi1/0/1"), normalize("gig 1/0/1"), normalize("Po10.100")
    ('GigabitEthernet1/0/1', 'GigabitEthernet1/0/1', 'Port-channel10.100')

    Raises ValueError for an empty name.
    """
    stripped = name.strip()
    if not stripped:
        raise ValueError("interface name is empty")
    match = _NAME_RE.fullmatch(stripped)
    if match is None:
        return stripped
    canonical = _canonical_type(match["type"])
    return f"{canonical or match['type']}{match['number']}"


_KIND_BY_TYPE: Final[dict[str, InterfaceKind]] = {
    "Port-channel": InterfaceKind.PORT_CHANNEL,
    "Vlan": InterfaceKind.SVI,
    "BDI": InterfaceKind.SVI,
    "Loopback": InterfaceKind.LOOPBACK,
    "Tunnel": InterfaceKind.TUNNEL,
    "Ethernet": InterfaceKind.PHYSICAL,
    "FastEthernet": InterfaceKind.PHYSICAL,
    "GigabitEthernet": InterfaceKind.PHYSICAL,
    "TwoGigabitEthernet": InterfaceKind.PHYSICAL,
    "FiveGigabitEthernet": InterfaceKind.PHYSICAL,
    "TenGigabitEthernet": InterfaceKind.PHYSICAL,
    "TwentyFiveGigE": InterfaceKind.PHYSICAL,
    "FortyGigabitEthernet": InterfaceKind.PHYSICAL,
    "HundredGigE": InterfaceKind.PHYSICAL,
    "Serial": InterfaceKind.PHYSICAL,
    "Cellular": InterfaceKind.PHYSICAL,
}


def interface_kind(name: str) -> InterfaceKind:
    """Best guess of an interface's kind from its name (subinterfaces count as ``other``)."""
    canonical = normalize(name)
    if canonical.lower().startswith(("mgmt", "management")):
        return InterfaceKind.MANAGEMENT
    match = _NAME_RE.fullmatch(canonical)
    if match is None or "." in match["number"]:
        return InterfaceKind.OTHER
    return _KIND_BY_TYPE.get(match["type"], InterfaceKind.OTHER)
