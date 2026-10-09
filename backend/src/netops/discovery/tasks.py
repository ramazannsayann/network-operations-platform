"""Celery task of the discovery module."""

import asyncio
import uuid

from celery import Task

from netops.core.settings import get_settings
from netops.discovery.engine import NoSshSlotError, run_discovery
from netops.workers.celery_app import celery_app

# How long to wait before trying again when all SSH sessions are in use.
_BUSY_RETRY_SECONDS = 30


@celery_app.task(name="netops.discover", bind=True, acks_late=True, max_retries=60)
def discover(self: Task, run_id: str) -> dict[str, str]:  # type: ignore[type-arg]
    """Execute one requested discovery run (see netops.discovery.engine).

    The whole run is this one task; its progress is in the run and job rows. A redelivered
    task starts the run over, which is safe: discovery converges on the same devices.
    """
    try:
        status = asyncio.run(run_discovery(uuid.UUID(run_id), get_settings()))
    except NoSshSlotError:
        raise self.retry(countdown=_BUSY_RETRY_SECONDS) from None
    return {"status": status.value}
