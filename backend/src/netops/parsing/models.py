"""Vendor-neutral results of parsing device output. Independent of SQLAlchemy.

Interface names are canonical (netops.core.ifname.normalize), MACs are lower-case
colon-separated, IP addresses are canonical strings and VLAN lists are fully expanded.
"""

from dataclasses import dataclass

from netops.db.enums import (
    Duplex,
    HsrpState,
    InterfaceKind,
    MacEntryType,
    NeighborProtocol,
    OsFamily,
    OspfNeighborState,
    RouteProtocol,
    StpPortRole,
    StpPortState,
    SwitchportMode,
    VlanStatus,
)


@dataclass(frozen=True, slots=True)
class Facts:
    hostname: str | None
    os_family: OsFamily
    os_version: str | None
    model: str | None
    # Chassis serial numbers, one per stack/VSS member, upper-case, in member order.
    serials: tuple[str, ...]
    uptime: str | None


@dataclass(frozen=True, slots=True)
class InventoryItem:
    name: str
    description: str
    pid: str | None
    serial: str | None
    # Stack member number for "Switch N" chassis entries.
    stack_member: int | None


@dataclass(frozen=True, slots=True)
class Neighbor:
    protocol: NeighborProtocol
    local_interface: str
    remote_name: str | None
    remote_mgmt_ip: str | None
    remote_port: str | None
    remote_platform: str | None
    remote_capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InterfaceStatus:
    """One interface from ``show interfaces``."""

    name: str
    kind: InterfaceKind
    admin_up: bool
    oper_up: bool
    err_disabled: bool
    description: str | None
    mac: str | None
    mtu: int | None
    speed_mbps: int | None
    duplex: Duplex | None
    # Primary address with prefix length, e.g. "10.0.20.2/24".
    address: str | None
    in_errors: int | None
    crc_errors: int | None
    late_collisions: int | None


@dataclass(frozen=True, slots=True)
class Switchport:
    interface: str
    mode: SwitchportMode
    access_vlan: int | None
    native_vlan: int | None
    allowed_vlans: tuple[int, ...] | None


@dataclass(frozen=True, slots=True)
class EtherChannel:
    port_channel: str
    protocol: str | None
    # (member interface, IOS status flag such as "P" bundled, "D" down, "s" suspended)
    members: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class IpInterface:
    interface: str
    address: str | None
    admin_up: bool
    oper_up: bool


@dataclass(frozen=True, slots=True)
class Vlan:
    vlan_id: int
    name: str | None
    status: VlanStatus
    ports: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MacEntry:
    vlan_id: int
    mac: str
    interface: str | None
    entry_type: MacEntryType


@dataclass(frozen=True, slots=True)
class ArpEntry:
    ip: str
    mac: str
    interface: str
    vrf: str | None


@dataclass(frozen=True, slots=True)
class Route:
    prefix: str
    protocol: RouteProtocol
    next_hop: str | None
    interface: str | None
    admin_distance: int | None
    metric: int | None
    vrf: str | None


@dataclass(frozen=True, slots=True)
class StpInstance:
    vlan_id: int
    # IOS bridge ID notation: priority (with sys-id-ext) and MAC, e.g. "24596 0011.2233.4455".
    root_bridge_id: str
    root_cost: int
    root_interface: str | None
    is_root: bool


@dataclass(frozen=True, slots=True)
class StpPort:
    vlan_id: int
    interface: str
    role: StpPortRole
    state: StpPortState
    cost: int


@dataclass(frozen=True, slots=True)
class SpanningTree:
    instances: tuple[StpInstance, ...]
    ports: tuple[StpPort, ...]


@dataclass(frozen=True, slots=True)
class HsrpGroup:
    interface: str
    group: int
    priority: int
    preempt: bool
    state: HsrpState
    virtual_ip: str
    # None when IOS prints "local" (this device) or "unknown"; see *_is_local.
    active_router: str | None
    active_is_local: bool
    standby_router: str | None
    standby_is_local: bool


@dataclass(frozen=True, slots=True)
class OspfNeighbor:
    router_id: str
    address: str
    interface: str
    state: OspfNeighborState
    # DR, BDR or DROTHER (the part after "/" in "FULL/DR"); None on point-to-point links.
    role: str | None


@dataclass(frozen=True, slots=True)
class OspfInterface:
    interface: str
    process: str
    area: int
    address: str | None
    cost: int | None
    state: str
