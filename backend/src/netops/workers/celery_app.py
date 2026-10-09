"""Celery application, using Redis as broker and result backend.

Start a worker with ``celery -A netops.workers.celery_app:celery_app worker``.
"""

from typing import Any

from celery import Celery, signals

from netops.core.logging import configure_logging
from netops.core.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "netops",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["netops.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    # Periodic jobs (e.g. M3 polling) will be registered here and run by `celery beat`.
    beat_schedule={},
)


@signals.setup_logging.connect
def _setup_logging(**_: Any) -> None:
    # Connecting this signal stops Celery from installing its own log handlers.
    configure_logging(settings.log_level, settings.log_format)
