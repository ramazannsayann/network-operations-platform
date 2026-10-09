"""Point-in-time state queries (ADR-0002, principle 2).

The state of device D for collection kind K at time T is the latest *successful* run of
kind K for D with ``started_at <= T``; the observation rows of that run are the state.
A run that started after T, is still running, or failed never counts, so a failed poll
does not make data disappear: the previous successful run still answers.

    run = await run_at(session, device_id, CollectionKind.MAC_TABLE, at=incident_time)
    macs = await state_at(session, MacEntry, device_id, at=incident_time)
    runs = await runs_at(session, CollectionKind.ARP_TABLE)  # latest per device, now
"""

import uuid
from collections.abc import Collection, Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, Select, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from netops.db.enums import CollectionKind, CollectionStatus
from netops.db.models import CollectionRun, Device, Observation


def _run_filters(
    kind: CollectionKind, at: datetime | None, include_partial: bool
) -> list[ColumnElement[bool]]:
    statuses = [CollectionStatus.SUCCESS]
    if include_partial:
        statuses.append(CollectionStatus.PARTIAL)
    filters = [CollectionRun.kind == kind, CollectionRun.status.in_(statuses)]
    if at is not None:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("`at` must be timezone-aware; use datetime.now(UTC) or similar")
        filters.append(CollectionRun.started_at <= at)
    return filters


async def run_at(
    session: AsyncSession,
    device_id: uuid.UUID,
    kind: CollectionKind,
    at: datetime | None = None,
    *,
    include_partial: bool = False,
) -> CollectionRun | None:
    """The run that defines device ``device_id``'s ``kind`` state at ``at`` (default: now).

    ``include_partial`` also accepts runs that finished with status ``partial``.
    Returns None if no qualifying run exists.
    """
    stmt = (
        select(CollectionRun)
        .where(CollectionRun.device_id == device_id, *_run_filters(kind, at, include_partial))
        .order_by(CollectionRun.started_at.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def runs_at(
    session: AsyncSession,
    kind: CollectionKind,
    at: datetime | None = None,
    *,
    device_ids: Collection[uuid.UUID] | None = None,
    include_partial: bool = False,
) -> dict[uuid.UUID, CollectionRun]:
    """``run_at`` for many devices at once: device id -> run (devices without one are absent).

    Uses one LATERAL lookup per device, each an index probe on
    (device_id, kind, started_at DESC), instead of sorting all runs of the kind.
    """
    latest = (
        select(CollectionRun)
        .where(CollectionRun.device_id == Device.id, *_run_filters(kind, at, include_partial))
        .order_by(CollectionRun.started_at.desc())
        .limit(1)
        .lateral("latest_run")
    )
    run = aliased(CollectionRun, latest)
    stmt = select(run).select_from(Device).join(latest, true())
    if device_ids is not None:
        stmt = stmt.where(Device.id.in_(device_ids))
    result = await session.scalars(stmt)
    return {r.device_id: r for r in result}


def observations_of[ObservationT: Observation](
    model: type[ObservationT], run: CollectionRun
) -> Select[ObservationT]:
    """SELECT the rows ``run`` wrote to ``model``'s table.

    Filtering on collected_at as well as run_id lets TimescaleDB skip every other chunk.
    """
    if run.kind != model.collection_kind:
        raise ValueError(
            f"{model.__name__} holds {model.collection_kind} data, not {run.kind} data"
        )
    return select(model).where(model.run_id == run.id, model.collected_at == run.started_at)


async def state_at[ObservationT: Observation](
    session: AsyncSession,
    model: type[ObservationT],
    device_id: uuid.UUID,
    at: datetime | None = None,
    *,
    include_partial: bool = False,
) -> Sequence[ObservationT]:
    """Rows of ``model`` that describe device ``device_id`` at ``at`` (default: now).

    Empty if the device has no qualifying run of ``model.collection_kind``.
    """
    run = await run_at(
        session, device_id, model.collection_kind, at, include_partial=include_partial
    )
    if run is None:
        return []
    return (await session.scalars(observations_of(model, run))).all()
