"""Path trace and impact analysis (M6)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from netops.api.problems import not_implemented, problems
from netops.api.schemas.diagnosis import ImpactAnalysis, PathTrace, PathTraceRequest
from netops.api.security import AUTHENTICATED
from netops.api.v1.common import At

router = APIRouter(
    prefix="/diagnosis",
    tags=["diagnosis"],
    dependencies=AUTHENTICATED,
    responses=problems(401, 422, 501),
)


@router.post("/path-trace", responses=problems(404))
async def trace_path(body: PathTraceRequest) -> PathTrace:
    """L2 and L3 hops from ``source`` to ``destination`` (at ``at``, default now).

    ACLs and firewall rules are never evaluated; the response always says so in
    ``warnings``. 404 if the source cannot be located.
    """
    raise not_implemented()


@router.get("/impact", responses=problems(404))
async def get_impact(
    device_id: Annotated[
        UUID | None, Query(description="Exactly one of device_id, link_id.")
    ] = None,
    link_id: Annotated[UUID | None, Query(description="Exactly one of device_id, link_id.")] = None,
    at: At = None,
) -> ImpactAnalysis:
    """Devices that would lose reachability from the platform if the device or link failed.

    422 unless exactly one of ``device_id`` and ``link_id`` is given.
    """
    raise not_implemented()
