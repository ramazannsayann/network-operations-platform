"""A small Cisco IOS / IOS-XE configuration parser: the indentation hierarchy.

Each line becomes a ``ConfigLine`` whose parent is the closest previous line with less
indentation (``interface Gi1/0/1`` -> `` switchport mode trunk``). Banners (text between
two delimiters, often ``^C``) are kept as opaque children of their ``banner`` line.
Certificate payloads under ``crypto pki certificate chain`` are marked, so they can be
collapsed.

Written for this project instead of ciscoconfparse(2), which are GPL-licensed (see
ADR-0007). It is used by the redactor now and by compliance checks later.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

_BANNER = re.compile(r"^banner \S+ (?P<rest>.*)$")


@dataclass(eq=False)
class ConfigLine:
    number: int  # 0-based position in the text
    text: str  # the line as it is, with its indentation
    indent: int
    parent: "ConfigLine | None" = None
    children: list["ConfigLine"] = field(default_factory=list)
    # Part of a banner text or a certificate payload: data, not commands.
    opaque: bool = False
    certificate_data: bool = False

    @property
    def command(self) -> str:
        return self.text.strip()

    def ancestors(self) -> Iterator["ConfigLine"]:
        """Parent, grandparent, ... (closest first)."""
        current = self.parent
        while current is not None:
            yield current
            current = current.parent

    def under(self, pattern: "re.Pattern[str]") -> bool:
        """Whether any ancestor's command matches ``pattern``."""
        return any(pattern.match(ancestor.command) for ancestor in self.ancestors())

    def walk(self) -> Iterator["ConfigLine"]:
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass
class ConfigTree:
    lines: list[ConfigLine]

    @property
    def roots(self) -> list[ConfigLine]:
        return [line for line in self.lines if line.parent is None]

    def find(self, pattern: str) -> list[ConfigLine]:
        """Command lines (not banner or certificate data) matching ``pattern`` (anchored)."""
        compiled = re.compile(pattern)
        return [line for line in self.lines if not line.opaque and compiled.match(line.command)]

    def section(self, pattern: str) -> list[ConfigLine]:
        """Top-level lines matching ``pattern``, e.g. ``interface \\S+``."""
        compiled = re.compile(pattern)
        return [line for line in self.roots if compiled.match(line.command)]


def _indent(text: str) -> int:
    return len(text) - len(text.lstrip(" "))


_CHAIN = re.compile(r"^crypto pki certificate chain ")


def parse(text: str) -> ConfigTree:
    lines: list[ConfigLine] = []
    stack: list[ConfigLine] = []  # open parents, outermost first
    banner: ConfigLine | None = None
    banner_end = ""
    raw_lines = text.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines.pop()  # the final newline

    for number, raw in enumerate(raw_lines):
        line = ConfigLine(number=number, text=raw, indent=_indent(raw))

        if banner is not None:
            line.opaque, line.parent = True, banner
            banner.children.append(line)
            lines.append(line)
            if banner_end in raw:
                banner = None
            continue

        command = line.command
        is_comment = command.startswith("!") or command == ""
        while stack and stack[-1].indent >= line.indent:
            stack.pop()
        if is_comment and line.indent == 0:
            stack.clear()
        line.parent = stack[-1] if stack else None
        if line.parent is not None:
            line.parent.children.append(line)
            parent = line.parent
            if (
                command != "quit"
                and parent.command.startswith("certificate")
                and parent.under(_CHAIN)
            ):
                line.opaque = line.certificate_data = True

        lines.append(line)
        if not is_comment and not line.opaque:
            stack.append(line)

        match = _BANNER.match(command) if line.indent == 0 else None
        if match:
            rest = match["rest"]
            delimiter = rest[:2] if rest.startswith("^") else rest[:1]
            if delimiter and delimiter not in rest[len(delimiter) :]:
                banner, banner_end = line, delimiter
    return ConfigTree(lines)
