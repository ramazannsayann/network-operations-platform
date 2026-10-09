"""Jobs: status of long-running operations started with 202 Accepted."""

from uuid import UUID

from fastapi import APIRouter

from netops.api.problems import not_implemented, problems
from netops.api.schemas.common import Job
from netops.api.security import AUTHENTICATED

router = APIRouter(
    prefix="/jobs", tags=["jobs"], dependencies=AUTHENTICATED, responses=problems(401, 422, 501)
)


@router.get("/{job_id}", responses=problems(404))
async def get_job(job_id: UUID) -> Job:
    raise not_implemented()
