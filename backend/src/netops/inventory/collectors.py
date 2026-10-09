"""One collector per collection kind: which commands it runs and how it stores the result.

A collector is pure bookkeeping on top of netops.parsing; running the commands is
netops.netaccess's job and the run lifecycle is netops.inventory.persistence's.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from ipaddress import ip_interface
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from netops.db.enums import CollectionKind
from netops.db.models import (
    ArpEntry,
    DeviceSerial,
    HsrpObservation,
    InterfaceAddress,
    InterfaceSnapshot,
    MacEntry,
    NeighborObservation,
    OspfNeighborObservation,
    RouteEntry,
    StpInstanceObservation,
    StpPortObservation,
    VlanObservation,
)
from netops.parsing.models import (
    ArpEntry as ParsedArpEntry,
)
from netops.parsing.models import (
    EtherChannel,
    Facts,
    HsrpGroup,
    InterfaceStatus,
    InventoryItem,
    Neighbor,
    OspfInterface,
    OspfNeighbor,
    Route,
    SpanningTree,
    Switchport,
    Vlan,
)
from netops.parsing.models import (
    MacEntry as ParsedMacEntry,
)

if TYPE_CHECKING:
    from netops.inventory.persistence import Context

Parsed = dict[str, Any]
Persist = Callable[["Context", Parsed], Awaitable[None]]


@dataclass(frozen=True)
class Collector:
    kind: CollectionKind
    commands: tuple[str, ...]
    # Without these the run fails; any other command may fail (the run is then partial).
    required: frozenset[str]
    persist: Persist


# --- facts ----------------------------------------------------------------------------------


async def persist_facts(ctx: "Context", parsed: Parsed) -> None:
    facts: Facts = parsed["show version"]
    inventory: list[InventoryItem] = parsed.get("show inventory", [])
    device = ctx.device
    device.hostname = facts.hostname or device.hostname
    device.vendor = "Cisco"
    device.model = facts.model or device.model
    device.os_family = facts.os_family
    device.os_version = facts.os_version or device.os_version

    members = {item.serial: item.stack_member for item in inventory if item.serial}
    for position, serial in enumerate(facts.serials, start=1):
        member = members.get(serial) or (position if len(facts.serials) > 1 else None)
        existing = await ctx.session.get(DeviceSerial, serial)
        if existing is None:
            ctx.session.add(
                DeviceSerial(
                    serial=serial,
                    device_id=device.id,
                    stack_member=member,
                    first_seen_at=ctx.seen_at,
                    last_seen_at=ctx.seen_at,
                )
            )
        elif existing.device_id != device.id:
            # The same chassis is known as another device (found under a second address).
            # Merging devices is discovery's job; keep the serial where it is.
            ctx.warnings.append(
                f"serial {serial} already belongs to device {existing.device_id}; not moved"
            )
        else:
            existing.stack_member = member
            existing.last_seen_at = ctx.seen_at


# --- interfaces -----------------------------------------------------------------------------


async def persist_interfaces(ctx: "Context", parsed: Parsed) -> None:
    statuses: list[InterfaceStatus] = parsed["show interfaces"]
    switchports: dict[str, Switchport] = {
        port.interface: port for port in parsed.get("show interfaces switchport", [])
    }
    channels: list[EtherChannel] | None = parsed.get("show etherchannel summary")

    snapshots = []
    addresses = []
    for status in statuses:
        interface = await ctx.interface(status.name)
        port = switchports.get(status.name)
        state = {
            "admin_up": status.admin_up,
            "oper_up": status.oper_up,
            "speed_mbps": status.speed_mbps,
            "duplex": status.duplex,
            "mtu": status.mtu,
            "switchport_mode": port.mode if port else None,
            "access_vlan": port.access_vlan if port else None,
            "native_vlan": port.native_vlan if port else None,
            "allowed_vlans": list(port.allowed_vlans)
            if port and port.allowed_vlans is not None
            else None,
            # The reason (bpduguard, psecure-violation, ...) needs another command.
            "err_disabled_reason": "unknown" if status.err_disabled else None,
            "in_errors": status.in_errors,
            "crc_errors": status.crc_errors,
            "late_collisions": status.late_collisions,
        }
        for column, value in state.items():
            setattr(interface, column, value)
        interface.name = status.name
        interface.kind = status.kind
        interface.description = status.description
        interface.mac = status.mac
        interface.last_seen_at = ctx.seen_at
        snapshots.append(ctx.observation(interface_id=interface.id, **state))
        if status.address:
            addresses.append(
                {
                    "interface_id": interface.id,
                    "address": status.address,
                    "is_secondary": False,
                    "first_seen_at": ctx.seen_at,
                    "last_seen_at": ctx.seen_at,
                }
            )

    if channels is not None:
        parent_of = {member: ch.port_channel for ch in channels for member, _ in ch.members}
        parents = {name: await ctx.interface(name) for name in set(parent_of.values())}
        # New port-channels must be inserted before members can point at them: the
        # self-referencing foreign key is invisible to the ORM's insert ordering.
        await ctx.session.flush()
        for name, interface in (await ctx.interfaces()).items():
            parent = parent_of.get(name)
            interface.parent_interface_id = parents[parent].id if parent else None

    await ctx.insert(InterfaceSnapshot, snapshots)
    if addresses:
        statement = pg_insert(InterfaceAddress).values(addresses)
        await ctx.session.execute(
            statement.on_conflict_do_update(
                index_elements=["interface_id", "address"],
                set_={"last_seen_at": statement.excluded.last_seen_at},
            )
        )


# --- neighbours, VLANs, MAC/ARP, routes ---------------------------------------------------------


async def persist_neighbors(ctx: "Context", parsed: Parsed) -> None:
    rows = []
    for command in ("show cdp neighbors detail", "show lldp neighbors detail"):
        neighbors: list[Neighbor] = parsed.get(command, [])
        for neighbor in neighbors:
            interface = await ctx.interface(neighbor.local_interface)
            rows.append(
                ctx.observation(
                    local_interface_id=interface.id,
                    protocol=neighbor.protocol,
                    remote_name=neighbor.remote_name,
                    remote_mgmt_ip=neighbor.remote_mgmt_ip,
                    remote_port=neighbor.remote_port,
                    remote_platform=neighbor.remote_platform,
                    remote_capabilities=list(neighbor.remote_capabilities) or None,
                )
            )
    await ctx.insert(NeighborObservation, rows)


async def persist_vlans(ctx: "Context", parsed: Parsed) -> None:
    vlans: list[Vlan] = parsed["show vlan brief"]
    await ctx.insert(
        VlanObservation,
        [ctx.observation(vlan_id=v.vlan_id, name=v.name, status=v.status) for v in vlans],
    )


async def persist_mac_table(ctx: "Context", parsed: Parsed) -> None:
    entries: list[ParsedMacEntry] = parsed["show mac address-table"]
    rows = []
    for entry in entries:
        interface = await ctx.interface(entry.interface) if entry.interface else None
        rows.append(
            ctx.observation(
                vlan_id=entry.vlan_id,
                mac=entry.mac,
                interface_id=interface.id if interface else None,
                entry_type=entry.entry_type,
            )
        )
    await ctx.insert(MacEntry, rows)


async def persist_arp_table(ctx: "Context", parsed: Parsed) -> None:
    entries: list[ParsedArpEntry] = parsed["show ip arp"]
    rows = []
    for entry in entries:
        interface = await ctx.interface(entry.interface)
        rows.append(
            ctx.observation(ip=entry.ip, mac=entry.mac, interface_id=interface.id, vrf=entry.vrf)
        )
    await ctx.insert(ArpEntry, rows)


async def persist_routes(ctx: "Context", parsed: Parsed) -> None:
    routes: list[Route] = parsed["show ip route"]
    rows = []
    for route in routes:
        interface = await ctx.interface(route.interface) if route.interface else None
        rows.append(
            ctx.observation(
                prefix=route.prefix,
                protocol=route.protocol,
                next_hop=route.next_hop,
                out_interface_id=interface.id if interface else None,
                admin_distance=route.admin_distance,
                metric=route.metric,
                vrf=route.vrf,
            )
        )
    await ctx.insert(RouteEntry, rows)


# --- spanning tree, HSRP, OSPF ------------------------------------------------------------------


async def persist_stp(ctx: "Context", parsed: Parsed) -> None:
    tree: SpanningTree = parsed["show spanning-tree"]
    instances = []
    for instance in tree.instances:
        root_port = (
            await ctx.interface(instance.root_interface) if instance.root_interface else None
        )
        instances.append(
            ctx.observation(
                vlan_id=instance.vlan_id,
                root_bridge_id=instance.root_bridge_id,
                root_cost=instance.root_cost,
                root_interface_id=root_port.id if root_port else None,
                is_root=instance.is_root,
                topology_changes=None,  # needs "show spanning-tree detail"
                last_topology_change_at=None,
            )
        )
    ports = []
    for port in tree.ports:
        interface = await ctx.interface(port.interface)
        ports.append(
            ctx.observation(
                vlan_id=port.vlan_id,
                interface_id=interface.id,
                role=port.role,
                state=port.state,
                cost=port.cost,
            )
        )
    await ctx.insert(StpInstanceObservation, instances)
    await ctx.insert(StpPortObservation, ports)


async def _own_address(ctx: "Context", interface_id: Any) -> str | None:
    """The device's own (most recently seen) address on an interface, without prefix."""
    address = await ctx.session.scalar(
        select(InterfaceAddress.address)
        .where(InterfaceAddress.interface_id == interface_id)
        .order_by(InterfaceAddress.last_seen_at.desc())
        .limit(1)
    )
    return str(ip_interface(address).ip) if address else None


async def persist_hsrp(ctx: "Context", parsed: Parsed) -> None:
    groups: list[HsrpGroup] = parsed["show standby brief"]
    rows = []
    for group in groups:
        interface = await ctx.interface(group.interface)
        own = None
        if group.active_is_local or group.standby_is_local:
            await ctx.session.flush()
            own = await _own_address(ctx, interface.id)
        rows.append(
            ctx.observation(
                interface_id=interface.id,
                group_number=group.group,
                virtual_ip=group.virtual_ip,
                state=group.state,
                priority=group.priority,
                preempt=group.preempt,
                active_router=own if group.active_is_local else group.active_router,
                standby_router=own if group.standby_is_local else group.standby_router,
            )
        )
    await ctx.insert(HsrpObservation, rows)


async def persist_ospf(ctx: "Context", parsed: Parsed) -> None:
    neighbors: list[OspfNeighbor] = parsed["show ip ospf neighbor"]
    interfaces: list[OspfInterface] = parsed["show ip ospf interface brief"]
    area_of = {i.interface: i.area for i in interfaces}
    rows = []
    for neighbor in neighbors:
        area = area_of.get(neighbor.interface)
        if area is None:
            ctx.warnings.append(
                f"OSPF neighbour {neighbor.router_id} on {neighbor.interface}: area unknown"
            )
            continue
        interface = await ctx.interface(neighbor.interface)
        rows.append(
            ctx.observation(
                neighbor_router_id=neighbor.router_id,
                neighbor_ip=neighbor.address,
                interface_id=interface.id,
                area=area,
                state=neighbor.state,
            )
        )
    await ctx.insert(OspfNeighborObservation, rows)


def _collector(kind: CollectionKind, persist: Persist, *commands: str, required: int) -> Collector:
    """``required``: how many of the leading commands must succeed."""
    return Collector(kind, commands, frozenset(commands[:required]), persist)


COLLECTORS: dict[CollectionKind, Collector] = {
    c.kind: c
    for c in (
        _collector(
            CollectionKind.FACTS, persist_facts, "show version", "show inventory", required=1
        ),
        _collector(
            CollectionKind.INTERFACES,
            persist_interfaces,
            "show interfaces",
            "show interfaces switchport",
            "show etherchannel summary",
            required=1,
        ),
        # Either protocol is enough; both failing fails the run.
        _collector(
            CollectionKind.NEIGHBORS,
            persist_neighbors,
            "show cdp neighbors detail",
            "show lldp neighbors detail",
            required=0,
        ),
        _collector(CollectionKind.VLANS, persist_vlans, "show vlan brief", required=1),
        _collector(
            CollectionKind.MAC_TABLE, persist_mac_table, "show mac address-table", required=1
        ),
        _collector(CollectionKind.ARP_TABLE, persist_arp_table, "show ip arp", required=1),
        _collector(CollectionKind.ROUTES, persist_routes, "show ip route", required=1),
        _collector(CollectionKind.STP, persist_stp, "show spanning-tree", required=1),
        _collector(CollectionKind.HSRP, persist_hsrp, "show standby brief", required=1),
        _collector(
            CollectionKind.OSPF,
            persist_ospf,
            "show ip ospf neighbor",
            "show ip ospf interface brief",
            required=2,
        ),
    )
}

# Collection kinds collect_device runs by default ("config" belongs to M4).
DEFAULT_KINDS: tuple[CollectionKind, ...] = tuple(COLLECTORS)
