"""Recognising CLI error answers instead of command output."""

import re

# Answers IOS gives when it does not run the command at all.
_ERROR_LINE = re.compile(
    r"^\s*% ?(Invalid input detected|Incomplete command|Ambiguous command|Unknown command"
    r"|Unrecognized command|Invalid command)",
    re.MULTILINE | re.IGNORECASE,
)
# The feature is switched off: an empty result, not an error.
_NOT_ENABLED = re.compile(r"^\s*% ?(CDP|LLDP) is not enabled", re.MULTILINE | re.IGNORECASE)


class CommandError(Exception):
    """The device did not run the command (unsupported, invalid or incomplete)."""

    def __init__(self, command: str, message: str) -> None:
        super().__init__(f"{command!r}: {message}")
        self.command = command
        self.message = message


def check_output(command: str, raw: str) -> bool:
    """Raise CommandError for an error answer; return False if the feature is disabled."""
    match = _ERROR_LINE.search(raw)
    if match:
        raise CommandError(command, match.group(0).strip())
    return _NOT_ENABLED.search(raw) is None
