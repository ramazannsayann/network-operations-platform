"""Celery tasks of the inventory module."""

import asyncio
import uuid
from datetime import UTC, datetime

from celery import Task
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from netops.core.settings import get_settings
from netops.db.enums import CollectionKind, CollectionTrigger
from netops.db.session import create_engine
from netops.inventory.cleanup import cleanup_collection_runs as cleanup
from netops.inventory.service import Busy
from netops.inventory.service import collect_device as collect
from netops.workers.celery_app import celery_app

# How long to wait before trying again when all SSH sessions are in use.
_BUSY_RETRY_SECONDS = 30


@celery_app.task(name="netops.collect_device", bind=True, acks_late=True, max_retries=20)
def collect_device(
    self: Task,  # type: ignore[type-arg]
    device_id: str,
    kinds: list[str] | None = None,
    trigger: str = CollectionTrigger.MANUAL.value,
) -> dict[str, str]:
    """Collect ``kinds`` (default: all) from one device; returns kind -> run status.

    Idempotent: every call records its own runs, and entity upserts converge. If the device
    is already being collected the call returns ``{"skipped": "device_locked"}``; if no SSH
    session slot is free it is retried later.
    """
    outcome = asyncio.run(
        collect(
            uuid.UUID(device_id),
            [CollectionKind(kind) for kind in kinds] if kinds else None,
            CollectionTrigger(trigger),
            get_settings(),
        )
    )
    if outcome is Busy.NO_SSH_SLOT:
        raise self.retry(countdown=_BUSY_RETRY_SECONDS)
    if isinstance(outcome, Busy):
        return {"skipped": outcome.value}
    return {kind.value: status.value for kind, status in outcome.items()}


@celery_app.task(name="netops.cleanup_collection_runs")
def cleanup_collection_runs() -> dict[str, int]:
    """Daily: delete expired collection runs and fail abandoned ones (see cleanup.py)."""

    async def run() -> dict[str, int]:
        engine = create_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await cleanup(session, datetime.now(UTC))
        finally:
            await engine.dispose()

    return asyncio.run(run())
