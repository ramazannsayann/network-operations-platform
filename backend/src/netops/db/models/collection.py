"""Collection runs: one row per collector execution against one device."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from netops.db.base import Base
from netops.db.enums import CollectionKind, CollectionStatus, CollectionTrigger
from netops.db.models._common import EntityMixin


class CollectionRun(EntityMixin, Base):
    """One execution of one collector (``kind``) against one device.

    The state of device D for kind K at time T is the latest successful run of kind K for D
    with started_at <= T, together with its observation rows (see netops.db.state).
    """

    __tablename__ = "collection_runs"
    __table_args__ = (
        # Target of every observation table's composite foreign key, which pins each
        # observation row to its run's device and start time.
        UniqueConstraint(
            "id", "device_id", "started_at", name="uq_collection_runs_id_device_id_started_at"
        ),
        CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)", name="finished_unless_running"
        ),
        CheckConstraint("finished_at >= started_at", name="finished_after_started"),
        CheckConstraint("status <> 'failed' OR error IS NOT NULL", name="failed_has_error"),
        # Deleting runs older than the observation retention (a periodic cleanup job).
        Index("ix_collection_runs_started_at", "started_at"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    kind: Mapped[CollectionKind]
    trigger: Mapped[CollectionTrigger]
    status: Mapped[CollectionStatus] = mapped_column(
        default=CollectionStatus.RUNNING, server_default=CollectionStatus.RUNNING.value
    )
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
    error: Mapped[str | None]


# "Latest run of kind K for device D before T" (netops.db.state) walks this index backwards.
Index(
    "ix_collection_runs_device_id_kind_started_at",
    CollectionRun.device_id,
    CollectionRun.kind,
    CollectionRun.started_at.desc(),
)
