"""Celery tasks of configuration management (M4)."""

import asyncio
import logging
import uuid
from typing import Any

from celery import Task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from netops.configmgmt.changes import ChangeReport
from netops.core.settings import get_settings
from netops.db.enums import CollectionKind, CollectionTrigger
from netops.db.models import Device
from netops.db.session import create_engine
from netops.inventory.service import Busy, collect_device
from netops.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# The device is being collected (or no SSH session is free): try again shortly, so the
# change is still recorded with its user and commands.
_BUSY_RETRY_SECONDS = 15


@celery_app.task(name="netops.config_change_event", bind=True, acks_late=True, max_retries=40)
def config_change_event(
    self: Task,  # type: ignore[type-arg]
    device_id: str,
    report: dict[str, Any],
) -> dict[str, str]:
    """Back up a device's configuration after syslog reported a change (events service).

    Idempotent: an unchanged configuration creates no version and no change row.
    """
    outcome = asyncio.run(
        collect_device(
            uuid.UUID(device_id),
            [CollectionKind.CONFIG],
            CollectionTrigger.EVENT,
            get_settings(),
            ChangeReport.from_json(report),
        )
    )
    if isinstance(outcome, Busy):
        raise self.retry(countdown=_BUSY_RETRY_SECONDS)
    return {kind.value: status.value for kind, status in outcome.items()}


async def managed_devices() -> list[uuid.UUID]:
    """Devices the platform logs in to: managed, with a credential profile."""
    engine = create_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine)() as session:
            rows = await session.scalars(
                select(Device.id)
                .where(Device.is_managed, Device.credential_profile_id.is_not(None))
                .order_by(Device.hostname)
            )
            return list(rows)
    finally:
        await engine.dispose()


@celery_app.task(name="netops.backup_configs")
def backup_configs() -> dict[str, int]:
    """Scheduled (CONFIG_BACKUP_SCHEDULE): queue a config collection of every managed device.

    A difference to the last version without a syslog report becomes an external change
    with an unknown user ("detected by scheduled backup").
    """
    devices = asyncio.run(managed_devices())
    for device_id in devices:
        celery_app.send_task(
            "netops.collect_device",
            kwargs={
                "device_id": str(device_id),
                "kinds": [CollectionKind.CONFIG.value],
                "trigger": CollectionTrigger.SCHEDULED.value,
            },
        )
    logger.info("configuration backups queued", extra={"devices": len(devices)})
    return {"queued": len(devices)}
