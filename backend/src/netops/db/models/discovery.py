"""Discovery runs (M1): one row per run, one item per address the run dealt with."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Index, Uuid, false, func
from sqlalchemy.dialects.postgresql import ARRAY, CIDR, INET
from sqlalchemy.orm import Mapped, mapped_column

from netops.db.base import Base
from netops.db.enums import DiscoveryItemStatus, DiscoverySource, JobStatus
from netops.db.models._common import EntityMixin, host_address


class DiscoveryRun(EntityMixin, Base):
    """A breadth-first CDP/LLDP discovery from seed addresses (proposal 7.1)."""

    __tablename__ = "discovery_runs"
    __table_args__ = (
        CheckConstraint("cardinality(seeds) > 0", name="has_seeds"),
        CheckConstraint("cardinality(allowed_subnets) > 0", name="has_allowed_subnets"),
        CheckConstraint("cardinality(credential_profile_ids) > 0", name="has_profiles"),
        CheckConstraint(
            "queued >= 0 AND scanned >= 0 AND found >= 0 AND new_devices >= 0"
            " AND skipped >= 0 AND errors >= 0",
            name="counters_non_negative",
        ),
        CheckConstraint("status <> 'failed' OR error IS NOT NULL", name="failed_has_error"),
        # Run history, newest first (GET /discovery/runs).
        Index("ix_discovery_runs_requested_at", "requested_at"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[JobStatus] = mapped_column(
        default=JobStatus.QUEUED, server_default=JobStatus.QUEUED.value
    )
    seeds: Mapped[list[str]] = mapped_column(ARRAY(INET))
    allowed_subnets: Mapped[list[str]] = mapped_column(ARRAY(CIDR))
    # Tried in this order, at most two per device. Not a foreign key (arrays cannot be);
    # the API checks the ids when the run is requested.
    credential_profile_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    requested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    # Progress counters (DiscoveryProgress in the API).
    queued: Mapped[int] = mapped_column(default=0, server_default="0")
    scanned: Mapped[int] = mapped_column(default=0, server_default="0")
    found: Mapped[int] = mapped_column(default=0, server_default="0")
    new_devices: Mapped[int] = mapped_column(default=0, server_default="0")
    skipped: Mapped[int] = mapped_column(default=0, server_default="0")
    errors: Mapped[int] = mapped_column(default=0, server_default="0")
    error: Mapped[str | None]


class DiscoveryRunItem(Base):
    """What a run did with one address: reached a device, skipped it, or failed."""

    __tablename__ = "discovery_run_items"
    __table_args__ = (
        host_address("address"),
        CheckConstraint("hop >= 0", name="hop_non_negative"),
        CheckConstraint("attempts BETWEEN 0 AND 2", name="at_most_two_attempts"),
        CheckConstraint(
            "address IS NOT NULL OR status = 'no_mgmt_ip'", name="address_unless_no_mgmt_ip"
        ),
        # Items of a run in BFS order (GET /discovery/runs/{id}); an address is dealt with
        # once per run.
        Index("ix_discovery_run_items_run_id_hop", "run_id", "hop"),
        Index(
            "uq_discovery_run_items_run_id_address",
            "run_id",
            "address",
            unique=True,
            postgresql_where="address IS NOT NULL",
        ),
        # Run items that mention a device (SET NULL when it is deleted).
        Index("ix_discovery_run_items_device_id", "device_id"),
        Index("ix_discovery_run_items_via_device_id", "via_device_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("discovery_runs.id", ondelete="CASCADE"))
    address: Mapped[str | None] = mapped_column(INET)
    hop: Mapped[int]
    # The device whose CDP/LLDP table pointed here (NULL for seeds).
    via_device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL")
    )
    via_interface: Mapped[str | None]
    source: Mapped[DiscoverySource]
    # As the neighbour advertised itself (CDP/LLDP), when known.
    neighbor_name: Mapped[str | None]
    platform: Mapped[str | None]
    status: Mapped[DiscoveryItemStatus]
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL")
    )
    # True if this run created the device.
    is_new: Mapped[bool] = mapped_column(default=False, server_default=false())
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    error: Mapped[str | None]
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())
