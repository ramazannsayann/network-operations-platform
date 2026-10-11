"""Change windows: group a device's CONFIG_I / CFGLOG messages into one change.

An operator's session produces one CFGLOG message per command and a CONFIG_I when leaving
configuration mode, often several sessions in a row. The first message opens a window for
the device; every further one extends it. It closes ``quiet`` seconds after the last
message, but at the latest ``maximum`` seconds after the first (a steady stream must not
postpone the backup forever). A closed window becomes one ``ChangeReport``; the events
service then asks for one ``config`` collection of the device.

Pure bookkeeping: the caller passes the monotonic time (``now``) and the wall-clock time of
each message (``at``), so tests need no sleeping.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from netops.configmgmt.changes import ChangeReport


@dataclass
class _Window:
    opened: float
    deadline: float
    first_at: datetime
    last_at: datetime
    username: str | None = None  # from CONFIG_I (who left config mode), else CFGLOG
    config_i_user: bool = False
    source_ip: str | None = None
    line: str | None = None
    commands: list[str] = field(default_factory=list)

    def report(self) -> ChangeReport:
        return ChangeReport(
            username=self.username,
            source_ip=self.source_ip,
            line=self.line,
            commands=tuple(self.commands),
            first_event_at=self.first_at,
            last_event_at=self.last_at,
        )


class ChangeDebouncer:
    def __init__(self, quiet: float, maximum: float) -> None:
        if quiet <= 0 or maximum < quiet:
            raise ValueError("need 0 < quiet <= maximum")
        self.quiet = quiet
        self.maximum = maximum
        self._windows: dict[uuid.UUID, _Window] = {}

    def __len__(self) -> int:
        return len(self._windows)

    def _window(self, device_id: uuid.UUID, at: datetime, now: float) -> _Window:
        window = self._windows.get(device_id)
        if window is None:
            window = _Window(opened=now, deadline=now, first_at=at, last_at=at)
            self._windows[device_id] = window
        window.deadline = min(now + self.quiet, window.opened + self.maximum)
        window.first_at = min(window.first_at, at)
        window.last_at = max(window.last_at, at)
        return window

    def configured(
        self,
        device_id: uuid.UUID,
        at: datetime,
        now: float,
        *,
        username: str | None = None,
        line: str | None = None,
        source_ip: str | None = None,
    ) -> None:
        """A %SYS-5-CONFIG_I: someone left configuration mode."""
        window = self._window(device_id, at, now)
        if username:
            window.username, window.config_i_user = username, True
        window.line = line or window.line
        window.source_ip = source_ip or window.source_ip

    def command(
        self,
        device_id: uuid.UUID,
        at: datetime,
        now: float,
        *,
        command: str,
        username: str | None = None,
    ) -> None:
        """A %PARSER-5-CFGLOG_LOGGEDCMD: one configuration command as entered."""
        window = self._window(device_id, at, now)
        window.commands.append(command)
        if username and not window.config_i_user and window.username is None:
            window.username = username

    def next_deadline(self) -> float | None:
        return min((w.deadline for w in self._windows.values()), default=None)

    def due(self, now: float) -> list[tuple[uuid.UUID, ChangeReport]]:
        """Close and return every window whose deadline has passed."""
        closed = [device for device, w in self._windows.items() if w.deadline <= now]
        return [(device, self._windows.pop(device).report()) for device in closed]

    def flush(self) -> list[tuple[uuid.UUID, ChangeReport]]:
        """Close every window (the service is stopping)."""
        windows, self._windows = self._windows, {}
        return [(device, window.report()) for device, window in windows.items()]
