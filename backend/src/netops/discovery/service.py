"""Requesting discovery runs (used by the API and the operator CLI)."""

import ipaddress
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from netops.db.enums import CredentialKind, JobKind, JobStatus
from netops.db.models import CredentialProfile, DiscoveryRun, Job
from netops.workers.jobs import new_job

# A run still queued or running after this long was abandoned (worker crash, lost message).
STALE_AFTER = timedelta(hours=2)
# Serialises run requests, so two concurrent requests cannot both start a run.
_REQUEST_LOCK = 0x4E4F_0003

ACTIVE = (JobStatus.QUEUED, JobStatus.RUNNING)


class DiscoveryInProgressError(Exception):
    def __init__(self, run_id: uuid.UUID) -> None:
        super().__init__(f"discovery run {run_id} is still in progress")
        self.run_id = run_id


class CredentialProfileError(ValueError):
    """A requested credential profile does not exist or is not an SSH profile."""


async def request_discovery(
    session: AsyncSession,
    seeds: Sequence[ipaddress.IPv4Address | ipaddress.IPv6Address],
    allowed_subnets: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network],
    credential_profile_ids: Sequence[uuid.UUID],
) -> tuple[DiscoveryRun, Job]:
    """Record a queued run and its job (committed). The caller enqueues ``netops.discover``.

    Raises DiscoveryInProgressError while another run is queued or running, and
    CredentialProfileError for unknown or non-SSH profiles.
    """
    if not seeds or not allowed_subnets or not credential_profile_ids:
        raise ValueError("seeds, allowed subnets and credential profiles are required")
    for profile_id in credential_profile_ids:
        profile = await session.get(CredentialProfile, profile_id)
        if profile is None:
            raise CredentialProfileError(f"credential profile {profile_id} does not exist")
        if profile.kind is not CredentialKind.SSH:
            raise CredentialProfileError(f"credential profile {profile.name!r} is not SSH")

    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _REQUEST_LOCK})
    now = datetime.now(UTC)
    await session.execute(
        update(DiscoveryRun)
        .where(DiscoveryRun.status.in_(ACTIVE), DiscoveryRun.requested_at < now - STALE_AFTER)
        .values(status=JobStatus.FAILED, finished_at=now, error="abandoned (no progress)")
    )
    active = await session.scalar(
        select(DiscoveryRun.id).where(DiscoveryRun.status.in_(ACTIVE)).limit(1)
    )
    if active is not None:
        await session.rollback()
        raise DiscoveryInProgressError(active)

    run_id = uuid.uuid4()
    job = new_job(JobKind.DISCOVERY, run_id)
    run = DiscoveryRun(
        id=run_id,
        job_id=job.id,
        status=JobStatus.QUEUED,
        seeds=[str(seed) for seed in dict.fromkeys(seeds)],
        allowed_subnets=[str(subnet) for subnet in dict.fromkeys(allowed_subnets)],
        credential_profile_ids=list(dict.fromkeys(credential_profile_ids)),
        requested_at=now,
    )
    session.add(job)
    await session.flush()
    session.add(run)
    await session.commit()
    return run, job
