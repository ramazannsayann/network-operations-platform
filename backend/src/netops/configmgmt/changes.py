"""What syslog reports about a configuration change, carried to the ``config`` collection.

The events service collects %SYS-5-CONFIG_I and %PARSER-5-CFGLOG_LOGGEDCMD messages of a
device into one ``ChangeReport`` per change window and hands it to the Celery task
``netops.config_change_event``; the report travels as JSON. Commands are already redacted
(the receiver redacts them before storing or forwarding anything).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from netops.configmgmt.redact import redact_commands
from netops.db.enums import ChangeOrigin


@dataclass(frozen=True)
class ChangeReport:
    username: str | None = None
    source_ip: str | None = None
    line: str | None = None  # vty0, console, ...
    commands: tuple[str, ...] = ()
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "source_ip": self.source_ip,
            "line": self.line,
            "commands": list(self.commands),
            "first_event_at": self.first_event_at.isoformat() if self.first_event_at else None,
            "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ChangeReport":
        def when(key: str) -> datetime | None:
            value = data.get(key)
            return datetime.fromisoformat(value) if value else None

        return cls(
            username=data.get("username"),
            source_ip=data.get("source_ip"),
            line=data.get("line"),
            commands=tuple(redact_commands(data.get("commands") or [])),
            first_event_at=when("first_event_at"),
            last_event_at=when("last_event_at"),
        )


def origin_of(report: "ChangeReport | None", platform_username: str | None) -> ChangeOrigin:
    """``platform`` only for the platform's own write account (M5); everything else,
    including changes nobody reported, is external."""
    if report is not None and platform_username and report.username == platform_username:
        return ChangeOrigin.PLATFORM
    return ChangeOrigin.EXTERNAL
