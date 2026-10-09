"""Topology (M1)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from netops.api.problems import not_implemented, problems
from netops.api.schemas.topology import Topology, TopologyChanges, TopologyLayer
from netops.api.security import AUTHENTICATED
from netops.api.v1.common import At

router = APIRouter(
    prefix="/topology",
    tags=["topology"],
    dependencies=AUTHENTICATED,
    responses=problems(401, 422, 501),
)


@router.get("")
async def get_topology(
    layer: TopologyLayer = TopologyLayer.L2,
    at: At = None,
    location_id: Annotated[
        UUID | None, Query(description="Only devices in this location and below.")
    ] = None,
) -> Topology:
    """The topology graph at ``at``.

    L2: devices and physical links; EtherChannel members are collapsed into one edge with a
    ``members`` list. L3: devices and the subnets their interfaces are in. Unmanaged and
    out-of-scope neighbours are included and flagged.
    """
    raise not_implemented()


@router.get("/changes")
async def get_topology_changes(
    since: Annotated[AwareDatetime, Query(description="Start of the comparison window.")],
    until: Annotated[
        AwareDatetime | None, Query(description="End of the window; defaults to now.")
    ] = None,
) -> TopologyChanges:
    """Devices and links that appeared or disappeared between ``since`` and ``until``."""
    raise not_implemented()
