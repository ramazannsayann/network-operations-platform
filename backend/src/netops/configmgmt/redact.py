"""Hide secrets in configuration text while keeping its lines.

Running-configs hold enable and user secrets (hashed or type 7), line passwords, SNMP
communities and v3 keys, TACACS+/RADIUS keys, IKE pre-shared keys, NTP and routing
protocol keys, key chains, wireless PSKs and certificates. Every config text that leaves
the backend (API, UI, logs, diffs) goes through this module; the stored copy in the local
Git repository stays complete for M5 (ADR-0007).

A secret value becomes ``MARKER``; the rest of the line (keywords, encryption type, key
numbers, addresses) stays, so a reader still sees what is configured and a diff still shows
that a secret line changed. Certificate payloads collapse to one ``CERTIFICATE_MARKER`` line.

Specific rules run first; a line no specific rule matched still goes through a generic
"password|secret <value>" rule, so an unknown command errs towards hiding.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from netops.configmgmt.parser import ConfigLine, parse

MARKER = "<redacted>"
CERTIFICATE_MARKER = "<certificate redacted>"

_TYPE = r"(?: [0-9])?"  # IOS encryption type: 0 clear, 5/8/9 hash, 6 AES, 7 Vigenère


@dataclass(frozen=True)
class Rule:
    """``pattern`` has a ``pre`` group (kept) followed by a ``secret`` group (hidden).
    ``parent``: the rule applies only to lines inside a matching block."""

    name: str
    pattern: re.Pattern[str]
    parent: re.Pattern[str] | None = None


def _rule(name: str, pattern: str, parent: str | None = None) -> Rule:
    return Rule(name, re.compile(pattern), re.compile(parent) if parent else None)


SPECIFIC_RULES: tuple[Rule, ...] = (
    _rule(
        "enable secret/password",
        rf"^(?P<pre>\s*enable(?: algorithm-type \S+)? (?:secret|password)(?: level \d+){_TYPE} )"
        r"(?P<secret>\S+)",
    ),
    _rule(
        "username secret/password",
        rf"^(?P<pre>\s*username \S+(?: \S+)*? (?:secret|password){_TYPE} )(?P<secret>\S+)",
    ),
    _rule(
        "line/trustpoint password",
        rf"^(?P<pre>\s*password{_TYPE} )(?!encryption\b)(?P<secret>\S+)",
    ),
    _rule("snmp community", r"^(?P<pre>\s*snmp-server community )(?P<secret>\S+)"),
    _rule(
        "snmp host community",
        r"^(?P<pre>\s*snmp-server host \S+(?: (?:traps|informs))?"
        r"(?: version (?:1|2c|3(?: (?:auth|noauth|priv))?))? )(?P<secret>\S+)",
    ),
    _rule(
        "snmp v3 auth key",
        r"^(?P<pre>\s*snmp-server user .*? auth \S+ )(?P<secret>\S+)",
    ),
    _rule(
        "snmp v3 priv key",
        r"^(?P<pre>\s*snmp-server user .*? priv (?:aes \d+|3des|des|\S+) )(?P<secret>\S+)",
    ),
    _rule(
        "tacacs/radius server key (legacy)",
        rf"^(?P<pre>\s*(?:tacacs-server|radius-server) .*?\bkey{_TYPE} )(?P<secret>\S+)",
    ),
    _rule(
        "tacacs/radius server key",
        rf"^(?P<pre>\s*key{_TYPE} )(?P<secret>\S+)",
        parent=r"^(?:tacacs server|radius server) ",
    ),
    _rule(
        "aaa server-private key",
        rf"^(?P<pre>\s*server-private \S+ .*?\bkey{_TYPE} )(?P<secret>\S+)",
    ),
    _rule(
        "isakmp key",
        r"^(?P<pre>\s*crypto isakmp key(?: [06])? )(?P<secret>\S+)",
    ),
    _rule(
        "keyring pre-shared-key",
        r"^(?P<pre>\s*pre-shared-key(?: address \S+(?: \S+)?| hostname \S+) key(?: [06])? )"
        r"(?P<secret>\S+)",
    ),
    _rule(
        "ikev2 pre-shared-key",
        r"^(?P<pre>\s*pre-shared-key(?: (?:local|remote))?(?: [06])? )"
        r"(?!address\b|hostname\b)(?P<secret>\S+)",
    ),
    _rule(
        "ntp authentication-key",
        r"^(?P<pre>\s*ntp authentication-key \d+ \S+ )(?P<secret>\S+)",
    ),
    _rule("key-string", rf"(?P<pre>\bkey-string{_TYPE} )(?P<secret>\S+)"),
    _rule(
        "ospf message-digest-key",
        rf"(?P<pre>\bmessage-digest-key \d+ md5{_TYPE} )(?P<secret>\S+)",
    ),
    _rule(
        "authentication-key",
        rf"^(?!\s*ntp )(?P<pre>.*?\bauthentication-key{_TYPE} )(?P<secret>\S+)",
    ),
    _rule("authentication text", r"(?P<pre>\bauthentication text )(?P<secret>\S+)"),
    _rule(
        "hsrp plain authentication",
        r"^(?P<pre>\s*standby(?: \d+)? authentication )(?!md5\b|text\b)(?P<secret>\S+)",
    ),
    _rule("wpa-psk", r"(?P<pre>\bwpa-psk (?:ascii|hex)(?: [0-9])? )(?P<secret>\S+)"),
    _rule("wlan psk", r"(?P<pre>\bset-key (?:ascii|hex)(?: [0-9])? )(?P<secret>\S+)"),
    _rule(
        "bgp neighbor password",
        rf"(?P<pre>\bneighbor \S+ password{_TYPE} )(?P<secret>\S+)",
    ),
)

# Anything still saying "password <value>" or "secret <value>". Not "password-encryption",
# "passwords", "nopassword" (no space after the keyword) and not "password encryption aes".
GENERIC_RULE = _rule(
    "generic password/secret",
    rf"(?P<pre>(?<![\w-])(?:password|secret){_TYPE} )(?!encryption\b)(?P<secret>\S+)",
)


def _hide(rule: Rule, text: str) -> tuple[str, bool]:
    def replace(match: re.Match[str]) -> str:
        return match["pre"] + MARKER

    result, count = rule.pattern.subn(replace, text)
    return result, count > 0


def redact_line(line: ConfigLine, *, context_free: bool = False) -> str | None:
    """The redacted text of one parsed line; None for certificate payload lines that are
    collapsed into the first one. ``context_free``: apply block-scoped rules everywhere (for
    commands seen without their parent block, e.g. in syslog); it can only hide more."""
    if line.certificate_data:
        first = line.parent is not None and line.parent.children[0] is line
        return f"{' ' * line.indent}{CERTIFICATE_MARKER}" if first else None
    if line.opaque:  # banner text
        return line.text
    text, matched = line.text, False
    for rule in SPECIFIC_RULES:
        if rule.parent is not None and not context_free and not line.under(rule.parent):
            continue
        text, hit = _hide(rule, text)
        matched = matched or hit
    if not matched:
        text, _ = _hide(GENERIC_RULE, text)
    return text


def redact_lines(text: str) -> list[str | None]:
    """One entry per line of ``text`` (same positions): the redacted line, or None where a
    certificate payload line is collapsed away."""
    return [redact_line(line) for line in parse(text).lines]


def redact(text: str) -> str:
    """The configuration with every secret replaced by ``MARKER``."""
    kept = [line for line in redact_lines(text) if line is not None]
    return "\n".join(kept) + "\n" if kept else ""


def redact_commands(commands: Sequence[str]) -> list[str]:
    """Commands as typed (archive log, M5): each on its own, without its parent block, so
    block-scoped rules apply to every command."""
    result = []
    for command in commands:
        lines = parse(command.strip("\n")).lines
        result.append(
            "\n".join(
                text
                for text in (redact_line(line, context_free=True) for line in lines)
                if text is not None
            )
        )
    return result
