"""The read-only guard: the only commands the read path may send to a device.

Allowed: ``show <something>``, ``terminal length 0`` and ``terminal width <n>``. Rejected:
everything else, and any command containing a line break or other control character
(which would let a second command ride along), ``;`` or ``|`` (output modifiers such as
``| redirect`` and ``| tee`` write files on the device), non-ASCII characters (look-alike
letters) or surrounding whitespace. IOS keyword abbreviations ("sh ver") are not accepted.
"""

import re
from collections.abc import Iterable

_SHOW = re.compile(r"show [!-~][ -~]*")
_TERMINAL_LENGTH = re.compile(r"terminal length 0")
_TERMINAL_WIDTH = re.compile(r"terminal width \d{1,3}")
_PRINTABLE_ASCII = re.compile(r"[ -~]+")
_SEPARATORS = (";", "|")


class ReadOnlyCommandError(ValueError):
    """A command that is not on the read-only allowlist was about to be sent."""


def check_read_only(command: object) -> str:
    """Return ``command`` unchanged if it is allowed; raise ReadOnlyCommandError otherwise."""
    if not isinstance(command, str):
        raise ReadOnlyCommandError(f"command must be a string, got {type(command).__name__}")
    if not command or not _PRINTABLE_ASCII.fullmatch(command):
        raise ReadOnlyCommandError(f"{command!r}: empty, or contains control/non-ASCII characters")
    if command != command.strip():
        raise ReadOnlyCommandError(f"{command!r}: leading or trailing whitespace")
    if any(separator in command for separator in _SEPARATORS):
        raise ReadOnlyCommandError(f"{command!r}: ';' and '|' are not allowed")
    lowered = command.lower()
    if not (
        _SHOW.fullmatch(lowered)
        or _TERMINAL_LENGTH.fullmatch(lowered)
        or _TERMINAL_WIDTH.fullmatch(lowered)
    ):
        raise ReadOnlyCommandError(f"{command!r}: not a read-only command")
    return command


def check_all(commands: Iterable[object]) -> tuple[str, ...]:
    """Check every command (all of them, before anything is sent); duplicates removed."""
    checked = [check_read_only(command) for command in commands]
    if not checked:
        raise ReadOnlyCommandError("no commands given")
    return tuple(dict.fromkeys(checked))
