"""Discovery runs (M1)."""

import ipaddress
from http import HTTPStatus
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from netops.api.problems import VALIDATION_ERROR, ProblemError, problems
from netops.api.schemas.common import DeviceRef, JobRef
from netops.api.schemas.discovery import (
    DiscoveredDevice,
    DiscoveryError,
    DiscoveryProgress,
    DiscoveryRun,
    DiscoveryRunCreate,
    DiscoveryRunPage,
    DiscoveryRunSummary,
    SkippedNeighbor,
    SkipReason,
)
from netops.api.security import AUTHENTICATED
from netops.api.v1.common import ACCEPTED, DEFAULT_LIMIT, Enqueue, Limit, Offset, Session
from netops.db import models as m
from netops.db.enums import DiscoveryItemStatus, JobStatus
from netops.discovery.service import (
    CredentialProfileError,
    DiscoveryInProgressError,
    request_discovery,
)

router = APIRouter(
    prefix="/discovery/runs",
    tags=["discovery"],
    dependencies=AUTHENTICATED,
    responses=problems(401, 422, 501),
)

DiscoveryRunSort = Literal["requested_at", "-requested_at"]

_SKIP_REASONS = {reason.value for reason in SkipReason}
_ERRORS = (DiscoveryItemStatus.AUTH_FAILED, DiscoveryItemStatus.UNREACHABLE)


@router.post("", status_code=HTTPStatus.ACCEPTED, responses=ACCEPTED | problems(409))
async def start_discovery(
    session: Session, enqueue: Enqueue, response: Response, body: DiscoveryRunCreate
) -> JobRef:
    """Start a CDP/LLDP discovery from the seeds. 409 while another run is in progress.

    The job's ``target_href`` is the new discovery run; progress is also pushed on the
    WebSocket (``discovery.progress``).
    """
    try:
        run, job = await request_discovery(
            session,
            [ipaddress.ip_address(str(seed)) for seed in body.seeds],
            [ipaddress.ip_network(str(net), strict=False) for net in body.allowed_subnets],
            body.credential_profile_ids,
        )
    except DiscoveryInProgressError as exc:
        raise ProblemError(HTTPStatus.CONFLICT, detail=str(exc)) from None
    except CredentialProfileError as exc:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY, detail=str(exc), type_=VALIDATION_ERROR
        ) from None
    enqueue("netops.discover", str(run.id))
    href = f"/api/v1/jobs/{job.id}"
    response.headers["Location"] = href
    return JobRef(
        id=job.id,
        kind=job.kind,
        status=job.status,
        href=href,
        target_href=f"/api/v1/discovery/runs/{run.id}",
    )


def _ip(address: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    return ipaddress.ip_address(address) if address else None


def _summary(run: m.DiscoveryRun) -> dict[str, object]:
    return {
        "id": run.id,
        "job_id": run.job_id,
        "status": run.status,
        "requested_at": run.requested_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "progress": DiscoveryProgress(
            queued=run.queued,
            scanned=run.scanned,
            found=run.found,
            skipped=run.skipped,
            errors=run.errors,
        ),
    }


@router.get("")
async def list_discovery_runs(
    session: Session,
    status: Annotated[list[JobStatus] | None, Query()] = None,
    sort: DiscoveryRunSort = "-requested_at",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> DiscoveryRunPage:
    conditions = [m.DiscoveryRun.status.in_(status)] if status else []
    total = await session.scalar(
        select(func.count()).select_from(m.DiscoveryRun).where(*conditions)
    )
    order = m.DiscoveryRun.requested_at
    runs = await session.scalars(
        select(m.DiscoveryRun)
        .where(*conditions)
        .order_by(order.desc() if sort.startswith("-") else order.asc(), m.DiscoveryRun.id)
        .limit(limit)
        .offset(offset)
    )
    return DiscoveryRunPage(
        items=[DiscoveryRunSummary.model_validate(_summary(run)) for run in runs],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}", responses=problems(404))
async def get_discovery_run(session: Session, run_id: UUID) -> DiscoveryRun:
    """Progress, devices found, neighbours skipped (e.g. out of scope) and errors."""
    run = await session.get(m.DiscoveryRun, run_id)
    if run is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, detail=f"Discovery run {run_id} does not exist.")
    items = list(
        await session.scalars(
            select(m.DiscoveryRunItem)
            .where(m.DiscoveryRunItem.run_id == run_id)
            .order_by(m.DiscoveryRunItem.hop, m.DiscoveryRunItem.id)
        )
    )
    device_ids = {i.device_id for i in items if i.device_id} | {
        i.via_device_id for i in items if i.via_device_id
    }
    refs = {
        d.id: DeviceRef(id=d.id, hostname=d.hostname, mgmt_ip=_ip(d.mgmt_ip))
        for d in await session.scalars(select(m.Device).where(m.Device.id.in_(device_ids)))
    }
    found = [
        DiscoveredDevice(device=refs[i.device_id], discovered_via=i.source, is_new=i.is_new)
        for i in items
        if i.status is DiscoveryItemStatus.DISCOVERED and i.device_id in refs
    ]
    skipped = [
        SkippedNeighbor(
            name=i.neighbor_name,
            mgmt_ip=_ip(i.address),
            platform=i.platform,
            seen_from=refs[i.via_device_id],
            local_interface=i.via_interface or "",
            reason=SkipReason(i.status.value),
        )
        for i in items
        if i.status.value in _SKIP_REASONS and i.via_device_id in refs
    ]
    errors = [
        DiscoveryError(
            target=ipaddress.ip_address(i.address),
            message=i.error or i.status.value,
            occurred_at=i.occurred_at,
        )
        for i in items
        if i.status in _ERRORS and i.address is not None
    ]
    return DiscoveryRun.model_validate(
        {
            **_summary(run),
            "request": {
                "seeds": run.seeds,
                "allowed_subnets": run.allowed_subnets,
                "credential_profile_ids": run.credential_profile_ids,
            },
            "found_devices": found,
            "skipped_neighbors": skipped,
            "errors": errors,
        }
    )
