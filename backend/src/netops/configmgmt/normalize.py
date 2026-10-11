"""Configuration text as stored and compared: without lines that change on their own.

IOS prints a header with the config size and timestamps of the last change and the last
NVRAM save; ``ntp clock-period`` is rewritten by the device as the clock drifts. None of
them is a configuration change, so they are dropped before hashing and committing.
"""

import hashlib
import re

_VOLATILE = re.compile(
    r"^(?:"
    r"Building configuration\.\.\."
    r"|Current configuration\s*:.*"
    r"|! Last configuration change at .*"
    r"|! NVRAM config last updated at .*"
    r"|! No configuration change since last restart.*"
    r"|! No NVRAM config update since last restart.*"
    r"|! Time: .*"
    r"|ntp clock-period \d+"
    r")$"
)


def normalize(raw: str) -> str:
    """The configuration without volatile lines, with ``\\n`` line ends, no trailing spaces
    and exactly one final newline."""
    lines = [line.rstrip() for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    kept = [line for line in lines if not _VOLATILE.match(line.strip())]
    while kept and not kept[0].strip():
        kept.pop(0)
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept) + "\n" if kept else ""


def content_hash(normalized: str) -> str:
    """sha256 (hex) of the normalized text: equal hashes mean no configuration change."""
    return hashlib.sha256(normalized.encode()).hexdigest()
