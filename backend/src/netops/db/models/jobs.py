"""Jobs: long-running operations started through the API (202 Accepted + GET /jobs/{id})."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from netops.db.base import Base
from netops.db.enums import JobKind, JobStatus
from netops.db.models._common import EntityMixin


class Job(EntityMixin, Base):
    """One device refresh or discovery run, as the API reports it.

    ``target_id`` is the device (device_refresh) or the discovery run (discovery); it is not
    a foreign key because the target table depends on the kind.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("status <> 'failed' OR error IS NOT NULL", name="failed_has_error"),
        CheckConstraint(
            "progress_completed >= 0 AND progress_total >= 0", name="progress_non_negative"
        ),
        # Jobs of one target, newest first (e.g. refreshes of a device).
        Index("ix_jobs_target_id_created_at", "target_id", "created_at"),
    )

    kind: Mapped[JobKind]
    status: Mapped[JobStatus] = mapped_column(
        default=JobStatus.QUEUED, server_default=JobStatus.QUEUED.value
    )
    target_id: Mapped[uuid.UUID]
    progress_completed: Mapped[int] = mapped_column(default=0, server_default="0")
    # NULL while the amount of work is unknown.
    progress_total: Mapped[int | None]
    progress_message: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    error: Mapped[str | None]
