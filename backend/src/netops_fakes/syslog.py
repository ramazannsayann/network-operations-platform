"""Syslog messages a fake device sends, in Cisco IOS format.

What the fake running-configs configure: facility local7, ``logging origin-id hostname``,
``service timestamps log datetime msec localtime show-timezone`` (clock in UTC) and, on the
IOS 15 switches only, ``service sequence-numbers``:

    <189>17: dist1: Oct 10 12:00:01.123 UTC: %SYS-5-CONFIG_I: Configured from console by ...
    <189>17: access1: 000017: Oct 10 12:00:01.123 UTC: %SYS-5-CONFIG_I: ...
"""

import re
import socket
from collections.abc import Iterable
from datetime import UTC, datetime

from netops_fakes.scenarios import Change
from netops_fakes.topology import Device

FACILITY_LOCAL7 = 23
_SEVERITY = re.compile(r"^%[A-Z0-9_]+(?:-[A-Z0-9_]+)?-(?P<severity>[0-7])-")


def format_message(device: Device, sequence: int, at: datetime, text: str) -> bytes:
    """One datagram; ``text`` starts with the %FACILITY-SEVERITY-MNEMONIC part."""
    match = _SEVERITY.match(text)
    severity = int(match.group("severity")) if match else 6
    at = at.astimezone(UTC)
    stamp = f"{at:%b} {at.day:>2} {at:%H:%M:%S}.{at.microsecond // 1000:03d} UTC"
    numbered = f"{sequence:06d}: " if device.os == "ios" else ""
    pri = FACILITY_LOCAL7 * 8 + severity
    return f"<{pri}>{sequence}: {device.name}: {numbered}{stamp}: {text}".encode()


def change_messages(change: Change, user: str, source_ip: str, line: str = "vty0") -> list[str]:
    """What a device with archive logging reports for a change, in order."""
    messages = [
        f"%PARSER-5-CFGLOG_LOGGEDCMD: User:{user}  logged command:{command}"
        for command in change.commands
    ]
    messages.extend(change.events)
    messages.append(f"%SYS-5-CONFIG_I: Configured from console by {user} on {line} ({source_ip})")
    return messages


def send(
    datagrams: Iterable[bytes], target: tuple[str, int], sock: socket.socket | None = None
) -> None:
    """Send over UDP; ``sock``: a bound socket to send from (tests map its port to a device)."""
    own = sock is None
    udp = sock or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        udp.connect(target)
        for datagram in datagrams:
            udp.send(datagram)
    finally:
        if own:
            udp.close()
