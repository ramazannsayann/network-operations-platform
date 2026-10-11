"""The ``config`` collector's storage step (netops.inventory.collectors).

Every ``config`` run normalizes ``show running-config`` and compares its hash with the
device's latest version. Unchanged: the run succeeds and nothing else is written. Changed:
the text is committed to the configuration repository, a ``config_versions`` row points at
the commit and, unless it is the device's first backup, a ``config_changes`` row records
the difference: with the user, source address and commands syslog reported for it, or
with an unknown user when a backup found it without any report (syslog lost, or no
``logging host`` on the device).

The commit happens before the database transaction commits. If the transaction fails,
the Git commit stays unreferenced and the next run commits the same text again: Git
history may hold a version the database does not know, never the other way round.
"""

import asyncio
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from netops.configmgmt.changes import ChangeReport, origin_of
from netops.configmgmt.normalize import content_hash, normalize
from netops.configmgmt.redact import redact_commands
from netops.configmgmt.store import ConfigStore
from netops.core.settings import get_settings
from netops.db.enums import CollectionTrigger, ConfigTrigger
from netops.db.models import ConfigChange, ConfigVersion, Device
from netops.parsing.models import RunningConfig

if TYPE_CHECKING:
    from netops.inventory.persistence import Context

COMMAND = "show running-config"

TRIGGERS = {
    CollectionTrigger.SCHEDULED: ConfigTrigger.SCHEDULED,
    CollectionTrigger.EVENT: ConfigTrigger.CHANGE_EVENT,
    CollectionTrigger.MANUAL: ConfigTrigger.MANUAL,
    CollectionTrigger.DISCOVERY: ConfigTrigger.MANUAL,
    CollectionTrigger.PRE_CHANGE: ConfigTrigger.PRE_CHANGE,
    CollectionTrigger.POST_CHANGE: ConfigTrigger.POST_CHANGE,
}


def commit_message(
    device: Device, trigger: ConfigTrigger, report: ChangeReport | None, first: bool
) -> str:
    name = device.hostname or str(device.mgmt_ip)
    subject = f"{name}: {'first backup' if first else 'new configuration'} ({trigger.value})"
    body = [f"Device: {name} ({device.mgmt_ip}, {device.id})", f"Trigger: {trigger.value}"]
    if report is not None:
        who = report.username or "unknown user"
        where = f" from {report.source_ip}" if report.source_ip else ""
        line = f" on {report.line}" if report.line else ""
        body.append(f"Changed by: {who}{where}{line}")
        if report.commands:
            body.append("Commands (redacted):")
            body.extend(f"  {command}" for command in redact_commands(report.commands))
    elif not first:
        body.append("Changed by: unknown (no syslog report)")
    return subject + "\n\n" + "\n".join(body) + "\n"


async def latest_version(context: "Context") -> ConfigVersion | None:
    version: ConfigVersion | None = await context.session.scalar(
        select(ConfigVersion)
        .where(ConfigVersion.device_id == context.device.id)
        .order_by(ConfigVersion.collected_at.desc())
        .limit(1)
    )
    return version


async def persist_config(context: "Context", parsed: dict[str, Any]) -> None:
    running: RunningConfig = parsed[COMMAND]
    text = normalize(running.text)
    digest = content_hash(text)
    previous = await latest_version(context)
    if previous is not None and previous.content_hash == digest:
        return  # unchanged: a successful run, no new version

    settings = get_settings()
    trigger = TRIGGERS[context.run.trigger]
    report = context.change_report
    device = context.device
    store = ConfigStore(settings.config_repo_path)
    message = commit_message(device, trigger, report, first=previous is None)
    commit = await asyncio.to_thread(store.commit, device.id, text, message, context.seen_at)

    version = ConfigVersion(
        id=uuid.uuid4(),
        device_id=device.id,
        collected_at=context.seen_at,
        git_commit=commit,
        content_hash=digest,
        trigger=trigger,
        size_bytes=len(text.encode()),
    )
    context.session.add(version)
    await context.session.flush()  # the change below references it
    if previous is None:
        return  # the first backup is the baseline, not a change

    detected_at: datetime = (
        report.first_event_at if report and report.first_event_at else context.seen_at
    )
    context.session.add(
        ConfigChange(
            id=uuid.uuid4(),
            device_id=device.id,
            detected_at=detected_at,
            origin=origin_of(report, settings.platform_write_username),
            username=report.username if report else None,
            source_ip=report.source_ip if report else None,
            commands=redact_commands(report.commands) if report else [],
            before_version_id=previous.id,
            after_version_id=version.id,
        )
    )
