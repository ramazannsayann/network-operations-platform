"""Inventory entities (M1/M2): locations, devices, serial numbers, interfaces, addresses."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, false
from sqlalchemy.dialects.postgresql import INET, MACADDR
from sqlalchemy.orm import Mapped, mapped_column

from netops.db.base import Base
from netops.db.enums import (
    DeviceRole,
    DeviceType,
    DiscoverySource,
    InterfaceKind,
    OsFamily,
    Reachability,
)
from netops.db.models._common import (
    EntityMixin,
    InterfaceStateMixin,
    SeenMixin,
    host_address,
    interface_state_checks,
)


class Location(EntityMixin, Base):
    """A place devices live in, nested e.g. campus > building > floor (maintained by users)."""

    __tablename__ = "locations"
    __table_args__ = (
        # No duplicate names under one parent; NULLS NOT DISTINCT covers top-level locations.
        UniqueConstraint(
            "parent_id",
            "name",
            name="uq_locations_parent_id_name",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("parent_id <> id", name="not_own_parent"),
    )

    name: Mapped[str]
    building: Mapped[str | None]
    floor: Mapped[str | None]
    description: Mapped[str | None]
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT")
    )


class Device(EntityMixin, SeenMixin, Base):
    """One logical network device; a stack or VSS pair is one device with several serials."""

    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint("hostname IS NOT NULL OR mgmt_ip IS NOT NULL", name="identifiable"),
        host_address("mgmt_ip"),
        CheckConstraint(r"sys_object_id ~ '^[0-9]+(\.[0-9]+)*$'", name="sys_object_id_format"),
        # Search and CDP/LLDP neighbour resolution by name.
        Index("ix_devices_hostname", "hostname"),
        # Devices of a location; also used when a location is deleted (SET NULL).
        Index("ix_devices_location_id", "location_id"),
    )

    # NULL until known: devices inferred from ARP have only an address at first.
    hostname: Mapped[str | None]
    mgmt_ip: Mapped[str | None] = mapped_column(INET, unique=True)
    device_type: Mapped[DeviceType] = mapped_column(
        default=DeviceType.UNKNOWN, server_default=DeviceType.UNKNOWN.value
    )
    role: Mapped[DeviceRole] = mapped_column(
        default=DeviceRole.UNKNOWN, server_default=DeviceRole.UNKNOWN.value
    )
    vendor: Mapped[str | None]
    model: Mapped[str | None]
    os_family: Mapped[OsFamily] = mapped_column(
        default=OsFamily.UNKNOWN, server_default=OsFamily.UNKNOWN.value
    )
    os_version: Mapped[str | None]
    sys_object_id: Mapped[str | None]
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL")
    )
    # Only managed devices are polled and configured (credentials, allowed subnets).
    is_managed: Mapped[bool] = mapped_column(default=False, server_default=false())
    reachability: Mapped[Reachability] = mapped_column(
        default=Reachability.UNKNOWN, server_default=Reachability.UNKNOWN.value
    )
    discovered_via: Mapped[DiscoverySource]
    last_polled_at: Mapped[datetime | None]


class DeviceSerial(SeenMixin, Base):
    """Chassis serial numbers. De-duplication key: one serial belongs to one device."""

    __tablename__ = "device_serials"
    __table_args__ = (
        # Stored canonical (trimmed, upper-case) so the same chassis always matches.
        CheckConstraint("serial <> '' AND serial = upper(btrim(serial))", name="serial_canonical"),
        CheckConstraint("stack_member >= 0", name="stack_member_non_negative"),
        Index("ix_device_serials_device_id", "device_id"),
    )

    serial: Mapped[str] = mapped_column(primary_key=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    # Switch number in a stack / VSS; NULL for a standalone chassis.
    stack_member: Mapped[int | None]


class Interface(EntityMixin, InterfaceStateMixin, SeenMixin, Base):
    """A device interface. The state columns hold the latest snapshot (see interface_snapshots)."""

    __tablename__ = "interfaces"
    __table_args__ = (
        # One row per interface; netops.core.ifname makes "Gi1/0/1" and
        # "GigabitEthernet1/0/1" the same name.
        UniqueConstraint(
            "device_id", "name_normalized", name="uq_interfaces_device_id_name_normalized"
        ),
        CheckConstraint("parent_interface_id <> id", name="not_own_parent"),
        *interface_state_checks(),
        # Members of a port-channel.
        Index("ix_interfaces_parent_interface_id", "parent_interface_id"),
        # "Is this MAC one of our own interfaces?" (host finder must skip device MACs).
        Index("ix_interfaces_mac", "mac"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    # Exactly as the device reported it, e.g. "Gi1/0/1".
    name: Mapped[str]
    # Canonical long form, e.g. "GigabitEthernet1/0/1" (netops.core.ifname.normalize).
    name_normalized: Mapped[str]
    kind: Mapped[InterfaceKind] = mapped_column(
        default=InterfaceKind.OTHER, server_default=InterfaceKind.OTHER.value
    )
    # The port-channel this physical interface is a member of.
    parent_interface_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interfaces.id", ondelete="SET NULL")
    )
    description: Mapped[str | None]
    mac: Mapped[str | None] = mapped_column(MACADDR)


class InterfaceAddress(SeenMixin, Base):
    """IP addresses configured on an interface, with their prefix length."""

    __tablename__ = "interface_addresses"
    __table_args__ = (
        # GiST on inet supports containment: "which interface's subnet contains 10.0.20.57?"
        # (address >>= ip), i.e. the gateway lookup for host finding and path tracing.
        Index(
            "ix_interface_addresses_address",
            "address",
            postgresql_using="gist",
            postgresql_ops={"address": "inet_ops"},
        ),
    )

    interface_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interfaces.id", ondelete="CASCADE"), primary_key=True
    )
    # Host address plus prefix length, e.g. 10.0.20.1/24.
    address: Mapped[str] = mapped_column(INET, primary_key=True)
    is_secondary: Mapped[bool] = mapped_column(default=False, server_default=false())
