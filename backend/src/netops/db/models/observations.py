"""Observation hypertables: what one collection run saw on one device.

Rows are append-only. Each class names the CollectionKind that produces it; every row of a
run has collected_at == run.started_at and device_id == run.device_id (see Observation).
Indexes starting with run_id serve "all rows of a run" and the ON DELETE CASCADE from
collection_runs; most double as a per-run uniqueness check.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import ARRAY, CIDR, INET, MACADDR
from sqlalchemy.orm import Mapped, mapped_column

from netops.db.enums import (
    CollectionKind,
    HsrpState,
    MacEntryType,
    NeighborProtocol,
    OspfNeighborState,
    RouteProtocol,
    StpPortRole,
    StpPortState,
    VlanStatus,
)
from netops.db.models._common import (
    InterfaceStateMixin,
    Observation,
    host_address,
    interface_state_checks,
    observation_table_args,
    vlan_id,
)


class InterfaceSnapshot(InterfaceStateMixin, Observation):
    """State of one interface in an ``interfaces`` run (status, speed, VLANs, error counters)."""

    __tablename__ = "interface_snapshots"
    __table_args__ = observation_table_args(
        *interface_state_checks(),
        Index(
            "uq_interface_snapshots_run_interface",
            "run_id",
            "interface_id",
            "collected_at",
            unique=True,
        ),
    )
    collection_kind = CollectionKind.INTERFACES

    interface_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("interfaces.id", ondelete="CASCADE"))


# History of one port: counter rates (CRC rising), flaps, err-disabled episodes.
Index(
    "ix_interface_snapshots_interface_id_collected_at",
    InterfaceSnapshot.interface_id,
    InterfaceSnapshot.collected_at.desc(),
)


class VlanObservation(Observation):
    """A VLAN defined on the device (``show vlan``)."""

    __tablename__ = "vlan_observations"
    __table_args__ = observation_table_args(
        vlan_id("vlan_id"),
        Index("uq_vlan_observations_run_vlan", "run_id", "vlan_id", "collected_at", unique=True),
    )
    collection_kind = CollectionKind.VLANS

    vlan_id: Mapped[int]
    name: Mapped[str | None]
    status: Mapped[VlanStatus | None]


class NeighborObservation(Observation):
    """A CDP/LLDP neighbour seen on a local interface; links are derived from these."""

    __tablename__ = "neighbor_observations"
    __table_args__ = observation_table_args(
        host_address("remote_mgmt_ip"),
        Index("ix_neighbor_observations_run_id", "run_id", "collected_at"),
    )
    collection_kind = CollectionKind.NEIGHBORS

    local_interface_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interfaces.id", ondelete="CASCADE")
    )
    protocol: Mapped[NeighborProtocol]
    remote_name: Mapped[str | None]
    remote_mgmt_ip: Mapped[str | None] = mapped_column(INET)
    # As advertised by the neighbour, e.g. "GigabitEthernet0/1" (normalise before matching).
    remote_port: Mapped[str | None]
    remote_platform: Mapped[str | None]
    # e.g. {"Router", "Switch", "IGMP"} (CDP) or {"bridge", "router"} (LLDP).
    remote_capabilities: Mapped[list[str] | None] = mapped_column(ARRAY(Text))


class MacEntry(Observation):
    """A MAC address table entry: MAC -> port in a VLAN."""

    __tablename__ = "mac_entries"
    __table_args__ = observation_table_args(
        vlan_id("vlan_id"),
        Index(
            "uq_mac_entries_run_vlan_mac", "run_id", "vlan_id", "mac", "collected_at", unique=True
        ),
    )
    collection_kind = CollectionKind.MAC_TABLE

    vlan_id: Mapped[int]
    mac: Mapped[str] = mapped_column(MACADDR)
    # NULL for entries without a port (CPU, drop).
    interface_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interfaces.id", ondelete="SET NULL")
    )
    entry_type: Mapped[MacEntryType]


# Host finder (MAC -> port) and "where has this MAC been?" history.
Index("ix_mac_entries_mac_collected_at", MacEntry.mac, MacEntry.collected_at.desc())


class ArpEntry(Observation):
    """An ARP entry on an L3 device: IP -> MAC on an interface."""

    __tablename__ = "arp_entries"
    __table_args__ = observation_table_args(
        host_address("ip"),
        Index("ix_arp_entries_run_id", "run_id", "collected_at"),
    )
    collection_kind = CollectionKind.ARP_TABLE

    ip: Mapped[str] = mapped_column(INET)
    mac: Mapped[str] = mapped_column(MACADDR)
    interface_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("interfaces.id", ondelete="CASCADE"))
    # NULL for the global routing table.
    vrf: Mapped[str | None]


# Host finder, IP -> MAC (first step of locating a host by IP).
Index("ix_arp_entries_ip_collected_at", ArpEntry.ip, ArpEntry.collected_at.desc())
# Host finder, MAC -> IP (when the user searches by MAC).
Index("ix_arp_entries_mac_collected_at", ArpEntry.mac, ArpEntry.collected_at.desc())


class RouteEntry(Observation):
    """A routing table entry; one row per next hop (ECMP routes have several)."""

    __tablename__ = "route_entries"
    __table_args__ = observation_table_args(
        host_address("next_hop"),
        CheckConstraint("admin_distance BETWEEN 0 AND 255", name="admin_distance_valid"),
        CheckConstraint("metric >= 0", name="metric_non_negative"),
        Index("ix_route_entries_run_id", "run_id", "collected_at"),
    )
    collection_kind = CollectionKind.ROUTES

    prefix: Mapped[str] = mapped_column(CIDR)
    protocol: Mapped[RouteProtocol]
    # NULL for directly connected/local routes.
    next_hop: Mapped[str | None] = mapped_column(INET)
    # NULL when the device does not resolve the next hop to an interface (recursive static).
    out_interface_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interfaces.id", ondelete="SET NULL")
    )
    # NULL when the source does not report them (firewall routes read via IP-FORWARD-MIB).
    admin_distance: Mapped[int | None]
    metric: Mapped[int | None] = mapped_column(BigInteger)
    # NULL for the global routing table.
    vrf: Mapped[str | None]


class StpInstanceObservation(Observation):
    """Per-VLAN spanning-tree instance (PVST+/Rapid-PVST+): who is root and how we reach it."""

    __tablename__ = "stp_instance_observations"
    __table_args__ = observation_table_args(
        vlan_id("vlan_id"),
        CheckConstraint("root_cost >= 0 AND topology_changes >= 0", name="counts_non_negative"),
        CheckConstraint("NOT is_root OR root_interface_id IS NULL", name="root_has_no_root_port"),
        Index(
            "uq_stp_instance_observations_run_vlan",
            "run_id",
            "vlan_id",
            "collected_at",
            unique=True,
        ),
    )
    collection_kind = CollectionKind.STP

    vlan_id: Mapped[int]
    # Root bridge ID as IOS prints it: priority (incl. VLAN) and MAC, e.g. "24596 0011.2233.4455".
    root_bridge_id: Mapped[str]
    root_cost: Mapped[int]
    # NULL on the root bridge itself.
    root_interface_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interfaces.id", ondelete="SET NULL")
    )
    is_root: Mapped[bool]
    topology_changes: Mapped[int | None] = mapped_column(BigInteger)
    last_topology_change_at: Mapped[datetime | None]


class StpPortObservation(Observation):
    """Spanning-tree role and state of one port in one VLAN."""

    __tablename__ = "stp_port_observations"
    __table_args__ = observation_table_args(
        vlan_id("vlan_id"),
        CheckConstraint("cost >= 0", name="cost_non_negative"),
        Index(
            "uq_stp_port_observations_run_vlan_interface",
            "run_id",
            "vlan_id",
            "interface_id",
            "collected_at",
            unique=True,
        ),
    )
    collection_kind = CollectionKind.STP

    vlan_id: Mapped[int]
    interface_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("interfaces.id", ondelete="CASCADE"))
    role: Mapped[StpPortRole]
    state: Mapped[StpPortState]
    cost: Mapped[int]


class HsrpObservation(Observation):
    """An HSRP group on an interface (``show standby``): which router is the active gateway."""

    __tablename__ = "hsrp_observations"
    __table_args__ = observation_table_args(
        host_address("virtual_ip"),
        host_address("active_router"),
        host_address("standby_router"),
        CheckConstraint("group_number BETWEEN 0 AND 4095", name="group_number_valid"),
        CheckConstraint("priority BETWEEN 0 AND 255", name="priority_valid"),
        Index(
            "uq_hsrp_observations_run_interface_group",
            "run_id",
            "interface_id",
            "group_number",
            "collected_at",
            unique=True,
        ),
    )
    collection_kind = CollectionKind.HSRP

    interface_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("interfaces.id", ondelete="CASCADE"))
    group_number: Mapped[int]
    virtual_ip: Mapped[str] = mapped_column(INET)
    state: Mapped[HsrpState]
    priority: Mapped[int]
    preempt: Mapped[bool]
    # The device's own address when it is active/standby itself ("local"); NULL if unknown.
    active_router: Mapped[str | None] = mapped_column(INET)
    standby_router: Mapped[str | None] = mapped_column(INET)


# Path tracing: "which router is currently the active gateway for 10.0.20.1?"
Index(
    "ix_hsrp_observations_virtual_ip_collected_at",
    HsrpObservation.virtual_ip,
    HsrpObservation.collected_at.desc(),
)


class OspfNeighborObservation(Observation):
    """An OSPF adjacency as seen from this device."""

    __tablename__ = "ospf_neighbor_observations"
    __table_args__ = observation_table_args(
        host_address("neighbor_router_id"),
        host_address("neighbor_ip"),
        CheckConstraint("area BETWEEN 0 AND 4294967295", name="area_valid"),
        Index(
            "uq_ospf_neighbor_observations_run_interface_neighbor",
            "run_id",
            "interface_id",
            "neighbor_router_id",
            "collected_at",
            unique=True,
        ),
    )
    collection_kind = CollectionKind.OSPF

    neighbor_router_id: Mapped[str] = mapped_column(INET)
    neighbor_ip: Mapped[str] = mapped_column(INET)
    interface_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("interfaces.id", ondelete="CASCADE"))
    # Area ID as a 32-bit number, so "0" and "0.0.0.0" are the same area.
    area: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[OspfNeighborState]
