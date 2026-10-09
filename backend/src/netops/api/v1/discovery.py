"""Discovery runs (M1)."""

from http import HTTPStatus
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query

from netops.api.problems import not_implemented, problems
from netops.api.schemas.common import JobRef
from netops.api.schemas.discovery import DiscoveryRun, DiscoveryRunCreate, DiscoveryRunPage
from netops.api.security import AUTHENTICATED
from netops.api.v1.common import ACCEPTED, DEFAULT_LIMIT, Limit, Offset
from netops.db.enums import JobStatus

router = APIRouter(
    prefix="/discovery/runs",
    tags=["discovery"],
    dependencies=AUTHENTICATED,
    responses=problems(401, 422, 501),
)

DiscoveryRunSort = Literal["requested_at", "-requested_at"]


@router.post("", status_code=HTTPStatus.ACCEPTED, responses=ACCEPTED | problems(409))
async def start_discovery(body: DiscoveryRunCreate) -> JobRef:
    """Start a CDP/LLDP discovery from the seeds. 409 while another run is in progress.

    The job's ``target_href`` is the new discovery run; progress is also pushed on the
    WebSocket (``discovery.progress``).
    """
    raise not_implemented()


@router.get("")
async def list_discovery_runs(
    status: Annotated[list[JobStatus] | None, Query()] = None,
    sort: DiscoveryRunSort = "-requested_at",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> DiscoveryRunPage:
    raise not_implemented()


@router.get("/{run_id}", responses=problems(404))
async def get_discovery_run(run_id: UUID) -> DiscoveryRun:
    """Progress, devices found, neighbours skipped (e.g. out of scope) and errors."""
    raise not_implemented()
