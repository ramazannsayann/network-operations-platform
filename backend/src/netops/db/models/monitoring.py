"""Monitoring and alarms (M3/M6): metrics, syslog/trap events, alarms and incidents."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Double,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from netops.db.base import Base
from netops.db.enums import AlarmState, EventKind, IncidentState, Severity
from netops.db.models._common import EntityMixin, host_address
from netops.db.timescale import EVENTS_RETENTION, METRICS_RETENTION, hypertable_info


class Metric(Base):
    """Time-series samples (SNMP polling), one value per row. Hypertable on ``time``.

    Narrow on purpose: no surrogate id. A sample is identified by (device, interface, name,
    time); the unique index treats a NULL interface (device-level metric) as a value.
    """

    __tablename__ = "metrics"
    __table_args__ = (
        # One sample per series and timestamp; also the index for device-level series
        # ("cpu_5min of device D over the last day") and for deleting a device's samples.
        Index(
            "uq_metrics_device_interface_name_time",
            "device_id",
            "interface_id",
            "name",
            "time",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        # Interface series ("if_in_octets of interface I") and deleting an interface's samples.
        Index(
            "ix_metrics_interface_id_name_time",
            "interface_id",
            "name",
            "time",
            postgresql_where=text("interface_id IS NOT NULL"),
        ),
        {"info": hypertable_info("time", METRICS_RETENTION)},
    )

    time: Mapped[datetime] = mapped_column()
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    # NULL for device-level metrics (CPU, memory, temperature).
    interface_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interfaces.id", ondelete="CASCADE")
    )
    # e.g. "cpu_5min", "mem_used_pct", "temp_celsius", "if_in_octets", "if_in_errors".
    name: Mapped[str] = mapped_column()
    value: Mapped[float] = mapped_column(Double)

    # The table has no primary key; the ORM identifies rows by the series key instead.
    __mapper_args__ = {"primary_key": [time, device_id, interface_id, name]}  # noqa: RUF012


class Event(Base):
    """A raw syslog message or SNMP trap as received. Hypertable on ``received_at``."""

    __tablename__ = "events"
    __table_args__ = (
        host_address("source_ip"),
        # RFC 5424 numeric codes: facility 0-23 (local7 = 23), severity 0 (emergency) - 7 (debug).
        CheckConstraint("facility BETWEEN 0 AND 23", name="facility_valid"),
        CheckConstraint("severity BETWEEN 0 AND 7", name="severity_valid"),
        {"info": hypertable_info("received_at", EVENTS_RETENTION)},
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    received_at: Mapped[datetime] = mapped_column(primary_key=True, server_default=func.now())
    source_ip: Mapped[str] = mapped_column(INET)
    # Resolved from source_ip (devices.mgmt_ip or an interface address); NULL if unknown.
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL")
    )
    kind: Mapped[EventKind]
    facility: Mapped[int | None] = mapped_column(SmallInteger)
    severity: Mapped[int | None] = mapped_column(SmallInteger)
    # Cisco "FACILITY-SEVERITY-MNEMONIC", e.g. "SYS-5-CONFIG_I", "LINK-3-UPDOWN".
    mnemonic: Mapped[str | None]
    message: Mapped[str]
    # Fields extracted by the parser (interface, user, source IP, trap varbinds, ...).
    parsed: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


# A device's event history (device page, change/fault correlation windows).
Index("ix_events_device_id_received_at", Event.device_id, Event.received_at.desc())


class Incident(EntityMixin, Base):
    """A group of alarms that M6 attributes to one root cause."""

    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(
            "(state = 'resolved') = (resolved_at IS NOT NULL)", name="resolved_iff_resolved_at"
        ),
        CheckConstraint("resolved_at >= opened_at", name="resolved_after_opened"),
    )

    title: Mapped[str]
    state: Mapped[IncidentState] = mapped_column(
        default=IncidentState.OPEN, server_default=IncidentState.OPEN.value
    )
    opened_at: Mapped[datetime] = mapped_column(server_default=func.now())
    resolved_at: Mapped[datetime | None]


class Alarm(EntityMixin, Base):
    """A detected problem with a lifecycle: open -> acknowledged -> cleared.

    Repeats of the same problem increment ``occurrence_count`` on the one non-cleared alarm
    with the same ``dedup_key`` (e.g. "if_down:<interface id>").
    """

    __tablename__ = "alarms"
    __table_args__ = (
        CheckConstraint("occurrence_count >= 1", name="occurrence_count_positive"),
        CheckConstraint("last_occurrence_at >= opened_at", name="last_occurrence_after_opened"),
        CheckConstraint(
            "state <> 'acknowledged' OR acknowledged_at IS NOT NULL", name="acknowledged_has_time"
        ),
        CheckConstraint(
            "(state = 'cleared') = (cleared_at IS NOT NULL)", name="cleared_iff_cleared_at"
        ),
        # At most one live (open or acknowledged) alarm per dedup key.
        Index(
            "uq_alarms_dedup_key_not_cleared",
            "dedup_key",
            unique=True,
            postgresql_where=text("state <> 'cleared'"),
        ),
        # The live alarm list, newest first.
        Index(
            "ix_alarms_opened_at_not_cleared",
            "opened_at",
            postgresql_where=text("state <> 'cleared'"),
        ),
        # Alarms grouped under an incident; also used when an incident is deleted (SET NULL).
        Index("ix_alarms_incident_id", "incident_id"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    interface_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interfaces.id", ondelete="SET NULL")
    )
    # Which rule raised it, e.g. "interface.down", "cpu.high", "ospf.neighbor_down".
    rule_key: Mapped[str]
    severity: Mapped[Severity]
    state: Mapped[AlarmState] = mapped_column(
        default=AlarmState.OPEN, server_default=AlarmState.OPEN.value
    )
    dedup_key: Mapped[str]
    occurrence_count: Mapped[int] = mapped_column(default=1, server_default="1")
    opened_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_occurrence_at: Mapped[datetime] = mapped_column(server_default=func.now())
    acknowledged_at: Mapped[datetime | None]
    # Free text until M7 adds users; then it becomes a reference to users.
    acknowledged_by: Mapped[str | None]
    cleared_at: Mapped[datetime | None]
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL")
    )
    summary: Mapped[str]
    # Rule-specific context (threshold, measured value, related event ids, ...).
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


# A device's alarm history (device page) and alarm correlation by device.
Index("ix_alarms_device_id_opened_at", Alarm.device_id, Alarm.opened_at.desc())
