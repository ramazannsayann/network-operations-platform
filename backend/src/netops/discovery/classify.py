"""What discovery can tell about a device from its own output or a neighbour's report."""

import ipaddress
import re

from netops.db.enums import DeviceType
from netops.parsing.models import Facts, Neighbor, Route

# Cisco router families (ISR, ASR, Catalyst 8000, CSR/C8000V, classic 1900/2900/3900...).
_ROUTER_MODEL = re.compile(
    r"^(?:ISR|ASR|C8\d{2,3}|C11\d{2}|CISCO\d{4}|CSR1000V|C8000V)", re.IGNORECASE
)
# Access points: they speak CDP but are managed through a controller, not over SSH here.
_AP_PLATFORM = re.compile(r"\bAIR-|\bC91\d{2}AX|\bCW91\d{2}", re.IGNORECASE)
_PHONE_PLATFORM = re.compile(r"\bIP Phone\b|\bCP-\d{4}", re.IGNORECASE)
# Device IDs such as "sw1(FOC1234X0AB)" (NX-OS) or "core1.lab.example.net".
_SERIAL_IN_NAME = re.compile(r"\(([A-Z0-9]{8,})\)$")


def device_type(facts: Facts, routes: list[Route] | None) -> DeviceType:
    """Router by model; otherwise an L3 switch if it routes (has a routing table), else a
    switch. L2 switches answer ``show ip route`` with "Default gateway is ...", which
    parses as an empty table."""
    if facts.model and _ROUTER_MODEL.match(facts.model):
        return DeviceType.ROUTER
    return DeviceType.L3_SWITCH if routes else DeviceType.SWITCH


def neighbor_type(neighbor: Neighbor) -> DeviceType:
    """Device type from what a neighbour advertises (for devices discovery cannot log in to)."""
    capabilities = {c.lower() for c in neighbor.remote_capabilities}
    platform = neighbor.remote_platform or ""
    if _AP_PLATFORM.search(platform) or capabilities & {"trans-bridge", "wlan-access-point"}:
        return DeviceType.AP
    routes = "router" in capabilities
    switches = bool(capabilities & {"switch", "bridge"})
    if routes and switches:
        return DeviceType.L3_SWITCH
    if routes:
        return DeviceType.ROUTER
    if switches:
        return DeviceType.SWITCH
    return DeviceType.UNKNOWN


def is_supported(neighbor: Neighbor) -> bool:
    """Whether discovery should log in: Cisco IOS/IOS-XE switches and routers only.

    APs, IP phones and anything that does not advertise switch/router capabilities is
    recorded (unsupported_platform) but never connected to.
    """
    platform = neighbor.remote_platform or ""
    if _PHONE_PLATFORM.search(platform):
        return False
    if neighbor_type(neighbor) not in (DeviceType.SWITCH, DeviceType.L3_SWITCH, DeviceType.ROUTER):
        return False
    # LLDP's system description, or CDP's platform; both start with "Cisco" on IOS devices.
    return platform == "" or "cisco" in platform.lower()


def model_from_platform(platform: str | None) -> str | None:
    """CDP platform "cisco WS-C2960X-48FPD-L" -> "WS-C2960X-48FPD-L"."""
    if not platform:
        return None
    words = platform.split()
    if len(words) == 2 and words[0].lower() == "cisco":
        return words[1]
    return None


def short_name(remote_name: str | None) -> str | None:
    """A neighbour's Device ID / System Name as a hostname: domain and serial removed."""
    if not remote_name:
        return None
    name = _SERIAL_IN_NAME.sub("", remote_name.strip())
    try:
        return str(ipaddress.ip_address(name))  # some devices advertise an address
    except ValueError:
        return name.split(".")[0] or None


def serial_in_name(remote_name: str | None) -> str | None:
    match = _SERIAL_IN_NAME.search(remote_name or "")
    return match.group(1).upper() if match else None
