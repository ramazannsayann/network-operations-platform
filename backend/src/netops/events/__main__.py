"""``python -m netops.events``: run the syslog receiver (the compose ``events`` service)."""

import asyncio
import logging
import signal
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker

from netops.configmgmt.changes import ChangeReport
from netops.core.logging import configure_logging
from netops.core.settings import get_settings
from netops.db.session import create_engine
from netops.events.receiver import EventsService

logger = logging.getLogger("netops.events")


async def enqueue_change(device_id: uuid.UUID, report: ChangeReport) -> None:
    """Ask a worker to back up the device's configuration (netops.config_change_event)."""
    from netops.workers.celery_app import celery_app

    await asyncio.to_thread(
        celery_app.send_task,
        "netops.config_change_event",
        kwargs={"device_id": str(device_id), "report": report.to_json()},
    )


async def serve() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url, pool_size=2, max_overflow=2)
    service = EventsService(
        settings, async_sessionmaker(engine, expire_on_commit=False), enqueue_change
    )
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopping.set)
    await service.start()
    try:
        await stopping.wait()
    finally:
        await service.stop()
        await engine.dispose()
        counters = {k: v for k, v in vars(service.stats).items() if isinstance(v, int)}
        logger.info("syslog receiver stopped", extra={"stats": counters})


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    asyncio.run(serve())


if __name__ == "__main__":
    main()
