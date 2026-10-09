"""Parsing device CLI output into vendor-neutral models (netops.parsing.models).

``parse(command, raw)`` is the entry point; ``PARSERS`` lists the supported commands.
"""

from netops.parsing.cisco_ios import PARSERS, ParseError, parse
from netops.parsing.errors import CommandError

__all__ = ["PARSERS", "CommandError", "ParseError", "parse"]
