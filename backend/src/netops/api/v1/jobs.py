"""Jobs: status of long-running operations started with 202 Accepted."""

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter

from netops.api.problems import JOB_FAILED, Problem, ProblemError, problems
from netops.api.schemas.common import Job, JobProgress
from netops.api.security import AUTHENTICATED
from netops.api.v1.common import Session
from netops.db import models as m
from netops.db.enums import JobKind, JobStatus

router = APIRouter(
    prefix="/jobs", tags=["jobs"], dependencies=AUTHENTICATED, responses=problems(401, 422, 501)
)

_TARGETS = {
    JobKind.DEVICE_REFRESH: "/api/v1/devices/{}",
    JobKind.DISCOVERY: "/api/v1/discovery/runs/{}",
}


@router.get("/{job_id}", responses=problems(404))
async def get_job(session: Session, job_id: UUID) -> Job:
    job = await session.get(m.Job, job_id)
    if job is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, detail=f"Job {job_id} does not exist.")
    started = job.status is not JobStatus.QUEUED
    return Job(
        id=job.id,
        kind=job.kind,
        status=job.status,
        target_href=_TARGETS[job.kind].format(job.target_id),
        progress=JobProgress(
            completed=job.progress_completed,
            total=job.progress_total,
            message=job.progress_message,
        )
        if started
        else None,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error=Problem(
            type=JOB_FAILED,
            title="Job failed",
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=job.error,
            instance=f"/api/v1/jobs/{job.id}",
        )
        if job.status is JobStatus.FAILED
        else None,
    )
