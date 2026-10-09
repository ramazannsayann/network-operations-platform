"""Job bookkeeping: the rows behind 202 Accepted responses and GET /api/v1/jobs/{id}.

The API creates a job (``queued``) and enqueues a Celery task with its id; the task marks it
``running``, may report progress, and finishes it as ``succeeded`` or ``failed``. Each step
commits, so the API sees progress while the task runs.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from netops.db.enums import JobKind, JobStatus
from netops.db.models import Job

_MAX_ERROR_LENGTH = 2000


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_job(kind: JobKind, target_id: uuid.UUID, total: int | None = None) -> Job:
    return Job(
        id=uuid.uuid4(),
        kind=kind,
        status=JobStatus.QUEUED,
        target_id=target_id,
        progress_completed=0,
        progress_total=total,
        created_at=utcnow(),
    )


async def job_started(session: AsyncSession, job_id: uuid.UUID) -> None:
    job = await session.get(Job, job_id)
    if job is not None:
        job.status = JobStatus.RUNNING
        job.started_at = job.started_at or utcnow()
        await session.commit()


async def job_progress(
    session: AsyncSession,
    job_id: uuid.UUID,
    completed: int,
    total: int | None,
    message: str | None,
) -> None:
    job = await session.get(Job, job_id)
    if job is not None:
        job.progress_completed = completed
        job.progress_total = total
        job.progress_message = message
        await session.commit()


async def job_finished(session: AsyncSession, job_id: uuid.UUID, error: str | None = None) -> None:
    """Mark the job ``succeeded``, or ``failed`` with ``error``."""
    job = await session.get(Job, job_id)
    if job is not None:
        job.status = JobStatus.FAILED if error else JobStatus.SUCCEEDED
        job.error = error[:_MAX_ERROR_LENGTH] if error else None
        job.started_at = job.started_at or utcnow()
        job.finished_at = utcnow()
        await session.commit()
