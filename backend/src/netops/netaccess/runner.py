"""``run_show``: send read-only commands to devices and collect their raw output."""

import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
    ReadTimeout,
)
from nornir.core.task import Result, Task
from paramiko.ssh_exception import SSHException

from netops.core.secrets import redact
from netops.core.settings import Settings, get_settings
from netops.netaccess.guard import check_all, check_read_only
from netops.netaccess.inventory import CONNECTION, DeviceAccess, build_nornir
from netops.netaccess.target import TargetResolver, resolve_target

logger = logging.getLogger(__name__)

_RETRY_BACKOFF_SECONDS = 2.0


@dataclass
class ShowResult:
    """What one device answered. ``error`` is set when no session could be established."""

    outputs: dict[str, str] = field(default_factory=dict)
    command_errors: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    # True when the device could not be reached at all (timeout, refused), as opposed to
    # e.g. an authentication failure on a reachable device.
    unreachable: bool = False
    # True when the device rejected the credentials (never retried, see ADR-0004).
    auth_failed: bool = False


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _show_task(task: Task, commands: tuple[str, ...], retries: int) -> Result:
    result = ShowResult()
    connection: Any = None
    for attempt in range(retries + 1):
        try:
            connection = task.host.get_connection(CONNECTION, task.nornir.config)
            break
        except NetmikoAuthenticationException:
            # Not retried: repeated failures can lock the account on the AAA server.
            result.error = "SSH authentication failed (check the credential profile)"
            result.auth_failed = True
            return Result(host=task.host, result=result)
        except (NetmikoTimeoutException, OSError) as exc:
            result.error = f"SSH connection failed: {_first_line(exc)}"
            result.unreachable = True
            if attempt < retries:
                time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
    if connection is None:
        return Result(host=task.host, result=result)
    result.error, result.unreachable = None, False

    for command in commands:
        check_read_only(command)  # second line of defence, right before sending
        try:
            result.outputs[command] = connection.send_command(command)
        except (ReadTimeout, NetmikoTimeoutException, SSHException, OSError, EOFError) as exc:
            # One failing command must not lose the others' output.
            result.command_errors[command] = f"{type(exc).__name__}: {_first_line(exc)}"
    return Result(host=task.host, result=result)


def run_show(
    accesses: Sequence[DeviceAccess],
    commands: Iterable[str],
    settings: Settings | None = None,
    resolve: TargetResolver | None = None,
) -> dict[UUID, ShowResult]:
    """Run read-only ``commands`` on every device (in parallel); never raises for a device.

    All commands are checked by the read-only guard before any connection is opened, so a
    forbidden command raises ReadOnlyCommandError without anything being sent. At most
    SSH_MAX_CONCURRENCY sessions are open at once. ``resolve`` overrides the installed
    connection-target resolver (netops.netaccess.target).
    """
    checked = check_all(commands)
    settings = settings or get_settings()
    if not accesses:
        return {}
    nornir = build_nornir(accesses, settings, resolve or resolve_target)
    try:
        aggregated = nornir.run(
            task=_show_task,
            commands=checked,
            retries=settings.ssh_retries,
            on_failed=True,
        )
    finally:
        nornir.close_connections(on_good=True, on_failed=True)

    results: dict[UUID, ShowResult] = {}
    for access in accesses:
        multi = aggregated[str(access.device_id)]
        if multi.failed or not isinstance(multi[0].result, ShowResult):
            failure = multi[0].exception
            result = ShowResult(error=f"SSH session failed: {_first_line(failure or Exception())}")
        else:
            result = multi[0].result
        # Nothing that reaches the database or logs may carry a password.
        secrets = access.secrets()
        if result.error:
            result.error = redact(result.error, secrets)
        result.command_errors = {
            command: redact(text, secrets) for command, text in result.command_errors.items()
        }
        if result.error:
            logger.warning(
                "device session failed", extra={"device": access.name, "error": result.error}
            )
        results[access.device_id] = result
    return results
