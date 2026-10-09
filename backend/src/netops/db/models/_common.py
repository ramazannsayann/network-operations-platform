"""Building blocks shared by the models: key columns, timestamps and reusable constraints."""

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Identity,
    Integer,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from netops.db.base import Base
from netops.db.enums import CollectionKind, Duplex, SwitchportMode
from netops.db.timescale import OBSERVATION_RETENTION, hypertable_info

# sort_order puts key columns first and bookkeeping timestamps last in CREATE TABLE.
_FIRST = -100
_LAST = 100


class EntityMixin:
    """Stable UUID identity for entity tables, whose rows are updated in place."""

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
        sort_order=_FIRST,
    )


class SeenMixin:
    """When collection first and most recently saw the entity on the network."""

    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now(), sort_order=_LAST)
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now(), sort_order=_LAST)


class Observation(Base):
    """Base of the append-only tables filled by one collection run (ADR-0002, principle 1).

    Every subclass is a TimescaleDB hypertable on ``collected_at``. All rows of a run carry
    the run's ``started_at`` as ``collected_at`` and the run's device as ``device_id``; the
    composite foreign key (run_id, device_id, collected_at) -> collection_runs(id, device_id,
    started_at) enforces both. The primary key is (id, collected_at) because TimescaleDB
    requires the partitioning column in every unique index. Nothing may reference these
    tables.
    """

    __abstract__ = True

    # The CollectionKind whose runs produce this table's rows (used by netops.db.state).
    collection_kind: ClassVar[CollectionKind]

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True, sort_order=_FIRST
    )
    collected_at: Mapped[datetime] = mapped_column(primary_key=True, sort_order=_FIRST + 1)
    run_id: Mapped[uuid.UUID] = mapped_column(sort_order=_FIRST + 2)
    device_id: Mapped[uuid.UUID] = mapped_column(sort_order=_FIRST + 3)


def observation_table_args(*args: Any) -> tuple[Any, ...]:
    """``__table_args__`` for an Observation subclass: run foreign key + hypertable marker."""
    return (
        ForeignKeyConstraint(
            ["run_id", "device_id", "collected_at"],
            ["collection_runs.id", "collection_runs.device_id", "collection_runs.started_at"],
            ondelete="CASCADE",
        ),
        *args,
        {"info": hypertable_info("collected_at", OBSERVATION_RETENTION)},
    )


class InterfaceStateMixin:
    """Mutable interface state. Snapshots record it per run; interfaces keep the latest copy."""

    admin_up: Mapped[bool | None] = mapped_column(sort_order=10)
    oper_up: Mapped[bool | None] = mapped_column(sort_order=10)
    speed_mbps: Mapped[int | None] = mapped_column(sort_order=10)
    duplex: Mapped[Duplex | None] = mapped_column(sort_order=10)
    mtu: Mapped[int | None] = mapped_column(sort_order=10)
    switchport_mode: Mapped[SwitchportMode | None] = mapped_column(sort_order=10)
    access_vlan: Mapped[int | None] = mapped_column(sort_order=10)
    native_vlan: Mapped[int | None] = mapped_column(sort_order=10)
    # Fully expanded ("1-3,10" is stored as {1,2,3,10}); empty for "none", NULL if unknown.
    allowed_vlans: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), sort_order=10)
    # e.g. "bpduguard", "psecure-violation", "link-flap"; NULL when not err-disabled.
    err_disabled_reason: Mapped[str | None] = mapped_column(sort_order=10)
    # Raw device counters (they reset on reboot or "clear counters"; rates are derived).
    in_errors: Mapped[int | None] = mapped_column(BigInteger, sort_order=10)
    crc_errors: Mapped[int | None] = mapped_column(BigInteger, sort_order=10)
    late_collisions: Mapped[int | None] = mapped_column(BigInteger, sort_order=10)


def interface_state_checks() -> tuple[CheckConstraint, ...]:
    """Value checks for the InterfaceStateMixin columns (NULL always passes)."""
    return (
        CheckConstraint(
            "access_vlan BETWEEN 1 AND 4094 AND native_vlan BETWEEN 1 AND 4094"
            " AND 1 <= ALL (allowed_vlans) AND 4094 >= ALL (allowed_vlans)",
            name="vlans_valid",
        ),
        CheckConstraint(
            "in_errors >= 0 AND crc_errors >= 0 AND late_collisions >= 0",
            name="counters_non_negative",
        ),
        CheckConstraint("speed_mbps >= 0 AND mtu > 0", name="speed_mtu_valid"),
    )


def host_address(column: str) -> CheckConstraint:
    """``column`` (inet) holds one host address, /32 or /128.

    PostgreSQL compares inet values including the netmask ('10.0.0.1/24' <> '10.0.0.1'),
    so host-address columns must not carry a prefix or lookups by IP silently miss.
    """
    return CheckConstraint(
        f"masklen({column}) = CASE family({column}) WHEN 4 THEN 32 ELSE 128 END",
        name=f"{column}_is_host",
    )


def vlan_id(column: str) -> CheckConstraint:
    """``column`` is a usable 802.1Q VLAN ID (0 and 4095 are reserved)."""
    return CheckConstraint(f"{column} BETWEEN 1 AND 4094", name=f"{column}_valid")
