"""Housekeeping of collection_runs (deferred in ADR-0002).

Observation hypertables drop their rows after OBSERVATION_RETENTION; the runs that
produced them would stay forever. Runs older than that retention are deleted once no
observation row references them any more. Runs stuck in ``running`` (their worker died)
are marked failed.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from netops.db.enums import CollectionStatus
from netops.db.models import CollectionRun, Observation
from netops.db.timescale import OBSERVATION_RETENTION

STALE_RUNNING_AFTER = timedelta(hours=2)
_BATCH_SIZE = 5000


async def cleanup_collection_runs(session: AsyncSession, now: datetime) -> dict[str, int]:
    abandoned = await session.execute(
        update(CollectionRun)
        .where(
            CollectionRun.status == CollectionStatus.RUNNING,
            CollectionRun.started_at < now - STALE_RUNNING_AFTER,
        )
        .values(
            status=CollectionStatus.FAILED,
            finished_at=now,
            error="abandoned: still running after 2 h (the worker probably stopped)",
        )
    )
    await session.commit()

    unreferenced = [
        ~exists().where(
            model.run_id == CollectionRun.id, model.collected_at == CollectionRun.started_at
        )
        for model in Observation.__subclasses__()
    ]
    deleted = 0
    while True:
        batch = (
            select(CollectionRun.id)
            .where(
                CollectionRun.started_at < now - OBSERVATION_RETENTION,
                CollectionRun.status != CollectionStatus.RUNNING,
                *unreferenced,
            )
            .limit(_BATCH_SIZE)
        )
        result = await session.execute(delete(CollectionRun).where(CollectionRun.id.in_(batch)))
        await session.commit()
        if not result.rowcount:  # type: ignore[attr-defined]
            break
        deleted += result.rowcount  # type: ignore[attr-defined]
    return {"deleted": deleted, "abandoned": abandoned.rowcount}  # type: ignore[attr-defined]
