"""Celery application, using Redis as broker and result backend.

Start a worker with ``celery -A netops.workers.celery_app:celery_app worker``.
"""

from typing import Any

from celery import Celery, signals
from celery.schedules import crontab

from netops.core.logging import configure_logging
from netops.core.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "netops",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["netops.workers.tasks", "netops.inventory.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    # Periodic jobs, run by `celery beat` (the scheduler service).
    beat_schedule={
        "cleanup-collection-runs": {
            "task": "netops.cleanup_collection_runs",
            "schedule": crontab(hour=3, minute=17),
        },
    },
)


@signals.setup_logging.connect
def _setup_logging(**_: Any) -> None:
    # Connecting this signal stops Celery from installing its own log handlers.
    configure_logging(settings.log_level, settings.log_format)
