"""Parse Cisco IOS / IOS-XE syslog datagrams.

The BSD-style format IOS sends, every part after the priority optional:

    <PRI>COUNTER: ORIGIN-ID: SEQUENCE: TIMESTAMP: %FACILITY-SEVERITY-MNEMONIC: text

COUNTER is the device's message counter (always sent by IOS), ORIGIN-ID comes from
``logging origin-id hostname|ip``, SEQUENCE from ``service sequence-numbers`` and the
timestamp from ``service timestamps log`` (datetime with or without msec, year and time
zone; ``*`` = clock not synchronized, ``.`` = synchronization lost; or uptime). RFC 5424
datagrams (``<PRI>1 2026-10-10T12:00:01.123Z host app - - - text``) are accepted too.

The mnemonic is reported as ``FACILITY-SEVERITY-MNEMONIC`` (``SYS-5-CONFIG_I``). Fields of
the messages M4 and M6 use are parsed: CONFIG_I (user, line, source address), CFGLOG
(user, command; redacted here, because without ``hidekeys`` the device logs keys as
typed), LINK/LINEPROTO up/down (interface, state).
"""

import re
from dataclasses import dataclass, field
from typing import Any

from netops.configmgmt.redact import redact_commands
from netops.core.ifname import normalize

CONFIG_I = "SYS-5-CONFIG_I"
CFGLOG = "PARSER-5-CFGLOG_LOGGEDCMD"

_MONTH_TIME = (
    r"[A-Z][a-z]{2} +\d{1,2}(?: \d{4})? \d{1,2}:\d{2}:\d{2}(?:\.\d{1,6})?"
    r"(?: [A-Za-z]{2,6}(?:[+-]\d{1,2}(?::?\d{2})?)?)?"
)
_UPTIME = r"\d+[ywdh]\d+[wdhm]|\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?"
_BSD = re.compile(
    r"^<(?P<pri>\d{1,3})>"
    r"(?:(?P<counter>\d+): )?"
    rf"(?:(?P<origin>(?!(?:\d+|{_UPTIME}): )[A-Za-z0-9][\w.-]*): )?"
    r"(?:(?P<sequence>\d+): )?"
    rf"(?:(?P<timestamp>[*.]?(?:{_MONTH_TIME}|{_UPTIME})): ?)?"
    r"(?P<rest>.*)$",
    re.DOTALL,
)
_RFC5424 = re.compile(
    r"^<(?P<pri>\d{1,3})>1 (?P<timestamp>\S+) (?P<origin>\S+) (?P<app>\S+) (?P<proc>\S+) "
    r"(?P<msgid>\S+) (?P<sd>-|(?:\[.*?\])+) ?(?P<rest>.*)$",
    re.DOTALL,
)
_MNEMONIC = re.compile(
    r"%(?P<facility>[A-Z][A-Z0-9_]*(?:-[A-Z][A-Z0-9_]*)*)-(?P<severity>[0-7])-"
    r"(?P<name>[A-Z0-9_]+): ?"
)
_CONFIG_I = re.compile(
    r"^Configured from (?P<via>\S+)(?: by (?P<who>[^\s,]+))?(?: on (?P<line>[^\s(]+))?"
    r"(?: ?\((?P<ip>[0-9A-Fa-f.:]+)\))?"
)
_CFGLOG = re.compile(r"^User:(?P<user>[^\s@]+)(?:@(?P<line>\S+))?\s+logged command:(?P<cmd>.*)$")
_LINK = re.compile(
    r"^(?:Line protocol on )?Interface (?P<interface>[^,]+), changed state to (?P<state>.+?)\s*$"
)
# "by console" / "by vty0 (192.0.2.7)": a line, not a user (no AAA username).
_LINE_NAME = re.compile(r"^(?:console|con\d*|vty\d+|tty\d+|aux\d*)$", re.IGNORECASE)


@dataclass
class SyslogMessage:
    facility: int | None
    severity: int | None
    mnemonic: str | None
    message: str
    parsed: dict[str, Any] = field(default_factory=dict)

    @property
    def is_config_change(self) -> bool:
        return self.mnemonic in (CONFIG_I, CFGLOG)


def parse_syslog(datagram: bytes) -> SyslogMessage:
    """Never raises: anything unrecognized becomes a message without mnemonic."""
    text = datagram.decode("utf-8", errors="replace").replace("\x00", "").strip()
    header: dict[str, Any] = {}
    facility = severity = None
    match = _RFC5424.match(text) or _BSD.match(text)
    if match:
        pri = int(match["pri"])
        if pri <= 191:
            facility, severity = pri // 8, pri % 8
        groups = match.groupdict()
        for key in ("counter", "sequence"):
            if groups.get(key):
                header[key] = int(groups[key])
        if groups.get("origin") and groups["origin"] != "-":
            header["hostname"] = groups["origin"]
        if groups.get("timestamp"):
            header["device_time"] = groups["timestamp"]
        text = match["rest"]

    found = _MNEMONIC.search(text)
    if found is None:
        return SyslogMessage(facility, severity, None, _safe(text), header)
    mnemonic = f"{found['facility']}-{found['severity']}-{found['name']}"
    if severity is None:
        severity = int(found["severity"])
    body = text[found.end() :].strip()
    fields = _fields(mnemonic, body)
    if mnemonic == CFGLOG and "command" in fields:
        body = body[: body.index("logged command:") + len("logged command:")] + fields["command"]
    return SyslogMessage(facility, severity, mnemonic, _safe(body), header | fields)


def _safe(text: str) -> str:
    """Errs towards hiding: a message that says "password <x>" loses <x>."""
    (redacted,) = redact_commands([text])
    return redacted


def _fields(mnemonic: str, body: str) -> dict[str, Any]:
    if mnemonic == CONFIG_I:
        match = _CONFIG_I.match(body)
        if not match:
            return {}
        who, line = match["who"], match["line"]
        if who and not line and _LINE_NAME.match(who):
            who, line = None, who
        return {
            key: value
            for key, value in {
                "via": match["via"],
                "user": who,
                "line": line,
                "source_ip": match["ip"],
            }.items()
            if value
        }
    if mnemonic == CFGLOG:
        match = _CFGLOG.match(body)
        if not match:
            return {}
        command = match["cmd"].strip()
        (redacted,) = redact_commands([command])
        fields: dict[str, Any] = {"user": match["user"], "command": redacted}
        if match["line"]:
            fields["line"] = match["line"]
        if command.startswith("!exec:"):
            fields["exec"] = True  # an exec command (enable, ...), not configuration
        return fields
    if mnemonic.startswith(("LINK-", "LINEPROTO-")):
        match = _LINK.match(body)
        if match:
            return {"interface": normalize(match["interface"]), "state": match["state"]}
    return {}
