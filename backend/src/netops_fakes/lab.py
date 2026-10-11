"""Derive what every device of a topology would report, as netops.parsing models.

``build(topology)`` computes, deterministically, the state the fake devices show: ports
(from links, hosts and SVIs), spanning tree (one PVST+ tree, the same for every VLAN),
MAC learning along the active tree, ARP, HSRP, OSPF adjacencies and routes (shortest
paths, with ECMP), and CDP/LLDP in both directions. ``netops_fakes.render`` turns these
models into CLI text; the round-trip test parses that text back and expects exactly
these models.
"""

import heapq
import ipaddress
from collections import deque
from dataclasses import dataclass, field

from netops.core.ifname import abbreviate, interface_kind
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
from netops.parsing import models as pm
from netops.parsing.normalize import mac as canonical_mac
from netops_fakes.topology import Device, Kind, Topology

UPTIME = "4 weeks, 2 days, 3 hours, 12 minutes"
DEFAULT_VLANS = (
    (1002, "fddi-default"),
    (1003, "token-ring-default"),
    (1004, "fddinet-default"),
    (1005, "trnet-default"),
)
OSPF_PROCESS = "1"

_SPEEDS = {
    "FastEthernet": 100,
    "Ethernet": 1000,
    "GigabitEthernet": 1000,
    "TwoGigabitEthernet": 2500,
    "FiveGigabitEthernet": 5000,
    "TenGigabitEthernet": 10_000,
    "TwentyFiveGigE": 25_000,
    "FortyGigabitEthernet": 40_000,
    "HundredGigE": 100_000,
}
_CDP_CAPABILITIES = {
    Kind.L3_SWITCH: ("Router", "Switch", "IGMP"),
    Kind.SWITCH: ("Switch", "IGMP"),
    Kind.ROUTER: ("Router", "Source-Route-Bridge"),
    Kind.AP: ("Trans-Bridge", "Source-Route-Bridge", "IGMP"),
}
_LLDP_CAPABILITIES = {
    Kind.L3_SWITCH: ("bridge", "router"),
    Kind.SWITCH: ("bridge",),
    Kind.ROUTER: ("router",),
}


def mac(device_index: int, number: int) -> str:
    """A locally administered, deterministic MAC address."""
    return f"02:00:00:{device_index:02x}:{number >> 8:02x}:{number & 0xFF:02x}"


def hsrp_mac(group: int) -> str:
    return f"00:00:0c:07:ac:{group & 0xFF:02x}"


def dotted(address: str) -> str:
    """'02:00:00:01:00:00' -> '0200.0001.0000' (IOS notation)."""
    digits = address.replace(":", "")
    return ".".join(digits[i : i + 4] for i in range(0, 12, 4))


def speed_of(name: str) -> int | None:
    kind = name.rstrip("0123456789/.:")
    return _SPEEDS.get(kind)


@dataclass
class Port:
    name: str
    kind: InterfaceKind
    number: int
    mac: str | None
    description: str | None = None
    address: ipaddress.IPv4Interface | None = None
    mode: SwitchportMode | None = None  # None: not a switchport (SVI, loopback, router)
    access_vlan: int | None = None
    native_vlan: int | None = None
    allowed_vlans: tuple[int, ...] | None = None
    channel: int | None = None
    peer: tuple[str, str] | None = None  # (device, port)
    edge: bool = False  # host or AP attached
    speed_mbps: int | None = None
    ospf_role: str | None = None  # DR / BDR / DROTHER on broadcast segments

    @property
    def l2(self) -> bool:
        return self.mode in (SwitchportMode.ACCESS, SwitchportMode.TRUNK)


@dataclass
class DeviceState:
    """One device's derived state. ``expected`` maps each supported command to the model
    our parser must produce from its rendered output."""

    device: Device
    index: int
    ports: dict[str, Port] = field(default_factory=dict)
    bridge_mac: str = ""
    vlan_ids: tuple[int, ...] = ()
    hsrp: list[pm.HsrpGroup] = field(default_factory=list)
    stp: pm.SpanningTree | None = None
    root_path_cost: int = 0
    macs: list[pm.MacEntry] = field(default_factory=list)
    arps: list[pm.ArpEntry] = field(default_factory=list)
    arp_ages: dict[str, str] = field(default_factory=dict)
    routes: list[pm.Route] = field(default_factory=list)
    gateway_of_last_resort: str | None = None
    ospf_neighbors: list[pm.OspfNeighbor] = field(default_factory=list)
    ospf_interfaces: list[pm.OspfInterface] = field(default_factory=list)
    cdp: list[pm.Neighbor] = field(default_factory=list)
    lldp: list[pm.Neighbor] = field(default_factory=list)
    default_gateway: str | None = None
    expected: dict[str, object] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.device.name

    @property
    def kind(self) -> Kind:
        return self.device.kind

    @property
    def is_switch(self) -> bool:
        return self.kind in (Kind.SWITCH, Kind.L3_SWITCH)

    @property
    def is_l3(self) -> bool:
        return self.kind in (Kind.L3_SWITCH, Kind.ROUTER)

    @property
    def os_family(self) -> OsFamily:
        return OsFamily.IOSXE if self.device.os == "iosxe" else OsFamily.IOS

    def add_port(self, name: str, **values: object) -> Port:
        if name in self.ports:
            port = self.ports[name]
            for key, value in values.items():
                setattr(port, key, value)
            return port
        number = len(self.ports) + 1
        kind = interface_kind(name)
        port = Port(
            name=name,
            kind=kind,
            number=number,
            mac=None if kind is InterfaceKind.LOOPBACK else mac(self.index, number),
            speed_mbps=speed_of(name) if kind is InterfaceKind.PHYSICAL else None,
        )
        for key, value in values.items():
            setattr(port, key, value)
        self.ports[name] = port
        return port

    def svis(self) -> list[Port]:
        return [p for p in self.ports.values() if p.kind is InterfaceKind.SVI]

    def svi(self, vlan: int) -> Port | None:
        return self.ports.get(f"Vlan{vlan}")


@dataclass
class Lab:
    topology: Topology
    devices: dict[str, DeviceState]
    stp_root: str | None = None
    # Switch-to-switch L2 edges in the active (non-blocked) spanning tree.
    stp_active: set[tuple[str, str, str, str]] = field(default_factory=set)

    def served(self) -> list[DeviceState]:
        """Devices a fake SSH server answers for."""
        return [d for d in self.devices.values() if not d.device.external]

    def expected_links(self) -> set[frozenset[tuple[str, str]]]:
        return {
            frozenset({(link.a.device, link.a.port), (link.b.device, link.b.port)})
            for link in self.topology.links
        }


# --- building ---------------------------------------------------------------------------------


def build(topology: Topology) -> Lab:
    devices = {
        d.name: DeviceState(device=d, index=i, bridge_mac=mac(i, 0))
        for i, d in enumerate(topology.devices, start=1)
    }
    lab = Lab(topology, devices)
    all_vlans = tuple(sorted(v.id for v in topology.vlans))
    for state in devices.values():
        if state.is_switch:
            state.vlan_ids = all_vlans
    _add_link_ports(lab, all_vlans)
    _add_host_ports(lab)
    _add_l3_interfaces(lab)
    _add_hsrp(lab)
    _spanning_tree(lab)
    _mac_tables(lab)
    _arp_tables(lab)
    _ospf_and_routes(lab)
    _neighbors(lab)
    for state in lab.served():
        state.expected = _expected(lab, state)
    return lab


def _add_link_ports(lab: Lab, all_vlans: tuple[int, ...]) -> None:
    topology = lab.topology
    for link in topology.links:
        a, b = lab.devices[link.a.device], lab.devices[link.b.device]
        ends = ((a, link.a.port, b, link.b.port), (b, link.b.port, a, link.a.port))
        if link.subnet is not None:
            hosts = list(link.subnet.hosts())
            for i, (local, port, remote, remote_port) in enumerate(ends):
                local.add_port(
                    port,
                    address=ipaddress.IPv4Interface(f"{hosts[i]}/{link.subnet.prefixlen}"),
                    mode=SwitchportMode.ROUTED if local.is_switch else None,
                    peer=(remote.name, remote_port),
                    description=f"to {remote.name} {abbreviate(remote_port)}",
                )
            continue
        for local, port, remote, remote_port in ends:
            description = f"to {remote.name} {abbreviate(remote_port)}"
            if not local.is_switch:
                local.add_port(port, peer=(remote.name, remote_port), description=description)
            elif remote.kind is Kind.AP:
                vlan = topology.vlan_of(remote.device.mgmt_ip)
                local.add_port(
                    port,
                    mode=SwitchportMode.ACCESS,
                    access_vlan=vlan.id if vlan else 1,
                    peer=(remote.name, remote_port),
                    description=description,
                    edge=True,
                )
            else:
                trunk = {
                    "mode": SwitchportMode.TRUNK,
                    "native_vlan": 1,
                    "allowed_vlans": all_vlans,
                }
                local.add_port(
                    port,
                    peer=(remote.name, remote_port),
                    description=description,
                    channel=link.channel,
                    **trunk,
                )
                if link.channel is not None:
                    channel = local.add_port(
                        f"Port-channel{link.channel}",
                        description=f"to {remote.name} Po{link.channel}",
                        **trunk,
                    )
                    member_speed = speed_of(port) or 0
                    channel.speed_mbps = member_speed


def _add_host_ports(lab: Lab) -> None:
    for state in lab.devices.values():
        for host in state.device.hosts:
            state.add_port(
                host.port,
                mode=SwitchportMode.ACCESS,
                access_vlan=host.vlan,
                description=f"host {host.ip}",
                edge=True,
            )


def _add_l3_interfaces(lab: Lab) -> None:
    topology = lab.topology
    cores = [d for d in lab.devices.values() if d.kind is Kind.L3_SWITCH]
    for state in lab.devices.values():
        device = state.device
        if state.kind is Kind.L3_SWITCH:
            position = cores.index(state)
            for vlan in topology.vlans:
                address = (
                    device.mgmt_ip
                    if device.mgmt_ip in vlan.subnet
                    else vlan.subnet.network_address + 2 + position
                )
                state.add_port(
                    f"Vlan{vlan.id}",
                    address=ipaddress.IPv4Interface(f"{address}/{vlan.subnet.prefixlen}"),
                    description=vlan.name,
                )
        elif state.kind is Kind.SWITCH:
            mgmt_vlan = topology.vlan_of(device.mgmt_ip)
            if mgmt_vlan is not None:
                prefix = mgmt_vlan.subnet.prefixlen
                state.add_port(
                    f"Vlan{mgmt_vlan.id}",
                    address=ipaddress.IPv4Interface(f"{device.mgmt_ip}/{prefix}"),
                    description=mgmt_vlan.name,
                )
                state.default_gateway = str(mgmt_vlan.gateway)
            for extra in device.extra_svis:
                extra_vlan = topology.vlan(extra.vlan)
                state.add_port(
                    f"Vlan{extra.vlan}",
                    address=ipaddress.IPv4Interface(f"{extra.ip}/{extra_vlan.subnet.prefixlen}"),
                    description=extra_vlan.name,
                )
        if device.loopback is not None and not device.external:
            state.add_port("Loopback0", address=ipaddress.IPv4Interface(f"{device.loopback}/32"))


def _add_hsrp(lab: Lab) -> None:
    cores = [d for d in lab.devices.values() if d.kind is Kind.L3_SWITCH]
    if len(cores) < 2:
        return
    for vlan in lab.topology.vlans:
        active = next((c for c in cores if vlan.id in c.device.hsrp_active), cores[0])
        standby = next(c for c in cores if c is not active)
        for core in cores:
            svi = core.svi(vlan.id)
            if svi is None or svi.address is None:
                continue
            is_active = core is active
            other = standby if is_active else active
            other_svi = other.svi(vlan.id)
            other_ip = str(other_svi.address.ip) if other_svi and other_svi.address else None
            role_is_standby = core is standby
            core.hsrp.append(
                pm.HsrpGroup(
                    interface=svi.name,
                    group=vlan.id,
                    priority=110 if is_active else 100,
                    preempt=is_active,
                    state=HsrpState.ACTIVE
                    if is_active
                    else (HsrpState.STANDBY if role_is_standby else HsrpState.LISTEN),
                    virtual_ip=str(vlan.gateway),
                    active_router=None if is_active else other_ip,
                    active_is_local=is_active,
                    standby_router=None if role_is_standby else other_ip,
                    standby_is_local=role_is_standby,
                )
            )


# --- spanning tree and MAC learning -------------------------------------------------------------


def _stp_cost(port: Port, state: DeviceState) -> int:
    if port.kind is InterfaceKind.PORT_CHANNEL:
        members = [p for p in state.ports.values() if p.channel == int(port.name[12:])]
        total = sum(p.speed_mbps or 0 for p in members)
    else:
        total = port.speed_mbps or 1000
    return max(1, 20_000_000 // total)


def _l2_edges(lab: Lab) -> list[tuple[str, str, str, str]]:
    """(device, port, peer device, peer port) for switch-to-switch L2 links; channels collapsed."""
    edges = []
    seen = set()
    for state in lab.devices.values():
        if not state.is_switch:
            continue
        for port in state.ports.values():
            if not port.l2 or port.peer is None or port.edge:
                continue
            peer_state = lab.devices[port.peer[0]]
            if not peer_state.is_switch:
                continue
            local = f"Port-channel{port.channel}" if port.channel else port.name
            remote_port = peer_state.ports[port.peer[1]]
            remote = (
                f"Port-channel{remote_port.channel}" if remote_port.channel else remote_port.name
            )
            key = frozenset({(state.name, local), (peer_state.name, remote)})
            if key not in seen:
                seen.add(key)
                edges.append((state.name, local, peer_state.name, remote))
    return edges


def _spanning_tree(lab: Lab) -> None:
    switches = {name: s for name, s in lab.devices.items() if s.is_switch and not s.device.external}
    if not switches:
        return
    edges = _l2_edges(lab)

    def bridge_id(name: str) -> tuple[int, str]:
        return (switches[name].device.stp_priority, switches[name].bridge_mac)

    root = min(switches, key=bridge_id)
    adjacency: dict[str, list[tuple[str, str, str, int]]] = {name: [] for name in switches}
    for a, a_port, b, b_port in edges:
        cost = _stp_cost(switches[a].ports[a_port], switches[a])
        adjacency[a].append((a_port, b, b_port, cost))
        adjacency[b].append((b_port, a, a_port, cost))

    distance = {root: 0}
    queue = [(0, bridge_id(root), root)]
    while queue:
        dist, _, name = heapq.heappop(queue)
        if dist > distance.get(name, 1 << 60):
            continue
        for _, peer, _, cost in adjacency[name]:
            if dist + cost < distance.get(peer, 1 << 60):
                distance[peer] = dist + cost
                heapq.heappush(queue, (dist + cost, bridge_id(peer), peer))

    root_port: dict[str, str] = {}
    for name in switches:
        if name == root or name not in distance:
            continue
        candidates = [
            (distance[peer] + cost, bridge_id(peer), peer_port, port)
            for port, peer, peer_port, cost in adjacency[name]
            if peer in distance
        ]
        root_port[name] = min(candidates)[3]

    for name, state in switches.items():
        state.root_path_cost = distance.get(name, 0)
        roles: dict[str, tuple[StpPortRole, StpPortState]] = {}
        for port_name, peer, _, _ in adjacency[name]:
            if root_port.get(name) == port_name:
                roles[port_name] = (StpPortRole.ROOT, StpPortState.FORWARDING)
            elif (distance.get(name, 0), bridge_id(name)) < (
                distance.get(peer, 0),
                bridge_id(peer),
            ):
                roles[port_name] = (StpPortRole.DESIGNATED, StpPortState.FORWARDING)
            else:
                roles[port_name] = (StpPortRole.ALTERNATE, StpPortState.BLOCKING)
        instances, ports = [], []
        root_state = switches[root]
        for vlan in state.vlan_ids:
            root_id = f"{root_state.device.stp_priority + vlan} {dotted(root_state.bridge_mac)}"
            instances.append(
                pm.StpInstance(
                    vlan_id=vlan,
                    root_bridge_id=root_id,
                    root_cost=state.root_path_cost,
                    root_interface=root_port.get(name),
                    is_root=name == root,
                )
            )
            for port in _stp_ports(state, vlan):
                role, port_state = roles.get(
                    port.name, (StpPortRole.DESIGNATED, StpPortState.FORWARDING)
                )
                ports.append(
                    pm.StpPort(
                        vlan_id=vlan,
                        interface=port.name,
                        role=role,
                        state=port_state,
                        cost=_stp_cost(port, state),
                    )
                )
        state.stp = pm.SpanningTree(instances=tuple(instances), ports=tuple(ports))
    lab.stp_root = root
    lab.stp_active = {
        (a, a_port, b, b_port)
        for a, a_port, b, b_port in edges
        if root_port.get(a) == a_port or root_port.get(b) == b_port
    }


def _stp_ports(state: DeviceState, vlan: int) -> list[Port]:
    ports = []
    for port in state.ports.values():
        if not port.l2 or port.channel is not None:
            continue
        trunk = port.mode is SwitchportMode.TRUNK and vlan in (port.allowed_vlans or ())
        if trunk or (port.mode is SwitchportMode.ACCESS and port.access_vlan == vlan):
            ports.append(port)
    return sorted(ports, key=lambda p: (p.kind is InterfaceKind.PORT_CHANNEL, p.number))


def _mac_tables(lab: Lab) -> None:
    tree: dict[str, list[tuple[str, str]]] = {}
    for a, a_port, b, b_port in lab.stp_active:
        tree.setdefault(a, []).append((a_port, b))
        tree.setdefault(b, []).append((b_port, a))

    def toward(start: str) -> dict[str, str]:
        """Switch -> local port of ``start`` on the tree path to it."""
        first: dict[str, str] = {}
        queue: deque[tuple[str, str | None]] = deque([(start, None)])
        seen = {start}
        while queue:
            node, via = queue.popleft()
            for port, peer in sorted(tree.get(node, [])):
                if peer not in seen:
                    seen.add(peer)
                    first[peer] = via or port
                    queue.append((peer, via or port))
        return first

    # Every MAC that switches learn: (vlan, mac, switch it is attached to, port there).
    endpoints: list[tuple[int, str, str, str | None]] = []
    for state in lab.devices.values():
        for index, host in enumerate(state.device.hosts, start=1):
            endpoints.append((host.vlan, _host_mac(state, index, host.mac), state.name, host.port))
        if state.is_switch:
            for svi in state.svis():
                endpoints.append((int(svi.name[4:]), svi.mac or "", state.name, None))
        for port in state.ports.values():
            if port.peer and lab.devices[port.peer[0]].kind is Kind.AP and port.access_vlan:
                ap = lab.devices[port.peer[0]]
                endpoints.append((port.access_vlan, mac(ap.index, 1), state.name, port.name))

    for state in lab.devices.values():
        if not state.is_switch or state.device.external:
            continue
        paths = toward(state.name)
        entries = []
        for vlan, address, attached, attached_port in endpoints:
            if attached == state.name:
                if attached_port is None:
                    continue  # its own SVI
                entries.append(pm.MacEntry(vlan, address, attached_port, MacEntryType.DYNAMIC))
            elif attached in paths:
                entries.append(pm.MacEntry(vlan, address, paths[attached], MacEntryType.DYNAMIC))
        state.macs = sorted(entries, key=lambda e: (e.vlan_id, e.mac))


def _host_mac(state: DeviceState, index: int, configured: str | None) -> str:
    if configured:
        return canonical_mac(configured) or configured
    return f"3c:52:82:{state.index:02x}:{index:02x}:00"


# --- ARP, OSPF and routing ----------------------------------------------------------------------


def _subnet_members(lab: Lab) -> dict[ipaddress.IPv4Network, list[tuple[str, str, str, str]]]:
    """Subnet -> (device, interface, ip, mac) of everything addressed in it."""
    members: dict[ipaddress.IPv4Network, list[tuple[str, str, str, str]]] = {}
    for state in lab.devices.values():
        for port in state.ports.values():
            if port.address is not None and port.kind is not InterfaceKind.LOOPBACK:
                members.setdefault(port.address.network, []).append(
                    (state.name, port.name, str(port.address.ip), port.mac or "")
                )
        for index, host in enumerate(state.device.hosts, start=1):
            members.setdefault(lab.topology.vlan(host.vlan).subnet, []).append(
                ("host", f"Vlan{host.vlan}", str(host.ip), _host_mac(state, index, host.mac))
            )
        if state.kind is Kind.AP:
            ap_vlan = lab.topology.vlan_of(state.device.mgmt_ip)
            if ap_vlan is not None:
                members.setdefault(ap_vlan.subnet, []).append(
                    (state.name, "", str(state.device.mgmt_ip), mac(state.index, 1))
                )
    return members


def _arp_tables(lab: Lab) -> None:
    members = _subnet_members(lab)
    for state in lab.served():
        entries: list[pm.ArpEntry] = []
        ages: dict[str, str] = {}
        for port in state.ports.values():
            if port.address is None or port.kind is InterfaceKind.LOOPBACK:
                continue
            own = str(port.address.ip)
            entries.append(pm.ArpEntry(own, port.mac or "", port.name, None))
            ages[own] = "-"
            if state.is_l3:
                for device, _, ip, address in members.get(port.address.network, []):
                    if ip != own and (device != state.name):
                        entries.append(pm.ArpEntry(ip, address, port.name, None))
                        ages[ip] = "5"
            elif state.default_gateway and port.address.network.overlaps(
                ipaddress.IPv4Network(f"{state.default_gateway}/32")
            ):
                vlan = int(port.name[4:])
                entries.append(pm.ArpEntry(state.default_gateway, hsrp_mac(vlan), port.name, None))
                ages[state.default_gateway] = "3"
        unique = {e.ip: e for e in entries}
        state.arps = sorted(unique.values(), key=lambda e: ipaddress.IPv4Address(e.ip))
        state.arp_ages = ages


def _ospf_and_routes(lab: Lab) -> None:
    routers = [s for s in lab.served() if s.is_l3 and s.device.loopback is not None]
    if not routers:
        return
    router_id = {s.name: str(s.device.loopback) for s in routers}

    def ospf_ports(state: DeviceState) -> list[Port]:
        return [p for p in state.ports.values() if p.address is not None]

    def adjacency_port(state: DeviceState, port: Port) -> bool:
        """Adjacencies form on routed links and the management VLAN SVI; other SVIs are passive."""
        if port.kind is InterfaceKind.SVI:
            vlan = lab.topology.vlan_of(state.device.mgmt_ip)
            return vlan is not None and port.name == f"Vlan{vlan.id}"
        return port.kind is InterfaceKind.PHYSICAL

    # Adjacencies: routers sharing a subnet on adjacency ports.
    by_subnet: dict[ipaddress.IPv4Network, list[tuple[DeviceState, Port]]] = {}
    for state in routers:
        for port in ospf_ports(state):
            if port.address and adjacency_port(state, port):
                by_subnet.setdefault(port.address.network, []).append((state, port))
    adjacent: dict[str, list[tuple[str, Port, Port]]] = {s.name: [] for s in routers}
    for attached in by_subnet.values():
        if len(attached) < 2:
            continue
        broadcast = attached[0][1].kind is InterfaceKind.SVI
        ranked = sorted(
            attached, key=lambda item: ipaddress.IPv4Address(router_id[item[0].name]), reverse=True
        )
        roles = {
            item[0].name: ("DR" if i == 0 else "BDR" if i == 1 else "DROTHER")
            for i, item in enumerate(ranked)
        }
        for state, port in attached:
            for peer, peer_port in attached:
                if peer is state:
                    continue
                adjacent[state.name].append((peer.name, port, peer_port))
                # Two DROTHERs stop at 2-WAY; every other pair becomes FULL.
                full = (roles[state.name], roles[peer.name]) != ("DROTHER", "DROTHER")
                state.ospf_neighbors.append(
                    pm.OspfNeighbor(
                        router_id=router_id[peer.name],
                        address=str(peer_port.address.ip) if peer_port.address else "",
                        interface=port.name,
                        state=OspfNeighborState.FULL if full else OspfNeighborState.TWO_WAY,
                        role=roles[peer.name] if broadcast else None,
                    )
                )
        if broadcast:
            for state, port in attached:
                port.ospf_role = roles[state.name]

    for state in routers:
        interfaces = []
        for port in ospf_ports(state):
            if port.kind is InterfaceKind.LOOPBACK:
                ospf_state = "LOOP"
            elif port.kind is InterfaceKind.PHYSICAL:
                ospf_state = "P2P"
            else:
                ospf_state = port.ospf_role or "DR"  # passive SVIs elect themselves
            if port.address is None or port.address.network not in _ospf_networks(lab, state.name):
                continue
            interfaces.append(
                pm.OspfInterface(
                    interface=port.name,
                    process=OSPF_PROCESS,
                    area=0,
                    address=str(port.address),
                    cost=1,
                    state=ospf_state,
                )
            )
        state.ospf_interfaces = interfaces

    _routes(lab, routers, adjacent, router_id)


def _ospf_networks(lab: Lab, name: str) -> list[ipaddress.IPv4Network]:
    """Networks a router advertises: every addressed interface except links outside the lab."""
    state = lab.devices[name]
    networks = []
    for port in state.ports.values():
        if port.address is None:
            continue
        if port.peer and lab.devices[port.peer[0]].device.external:
            continue  # the provider link is not in OSPF
        networks.append(port.address.network)
    return networks


def _routes(
    lab: Lab,
    routers: list[DeviceState],
    adjacent: dict[str, list[tuple[str, Port, Port]]],
    router_id: dict[str, str],
) -> None:
    advertised: dict[ipaddress.IPv4Network, set[str]] = {}
    for state in routers:
        for network in _ospf_networks(lab, state.name):
            advertised.setdefault(network, set()).add(state.name)
    asbr = next(
        (
            s.name
            for s in routers
            if any(p.peer and lab.devices[p.peer[0]].device.external for p in s.ports.values())
        ),
        None,
    )

    for state in routers:
        distance = _hop_distances(state.name, adjacent)
        connected = {p.address.network: (p, p.address) for p in state.ports.values() if p.address}
        routes: list[pm.Route] = []
        # Default route: a static route to the provider on the ASBR, OSPF E2 everywhere else.
        provider_port = next(
            (
                p
                for p in state.ports.values()
                if p.peer and lab.devices[p.peer[0]].device.external and p.address
            ),
            None,
        )
        if provider_port is not None and provider_port.address is not None:
            peer = lab.devices[provider_port.peer[0]].ports[provider_port.peer[1]]  # type: ignore[index]
            next_hop = str(peer.address.ip) if peer.address else None
            routes.append(pm.Route("0.0.0.0/0", RouteProtocol.STATIC, next_hop, None, 1, 0, None))
            state.gateway_of_last_resort = next_hop
        elif asbr is not None and asbr in distance:
            hops = _next_hops(state.name, {asbr}, distance, adjacent)
            for peer_ip, interface in hops:
                routes.append(
                    pm.Route("0.0.0.0/0", RouteProtocol.OSPF, peer_ip, interface, 110, 1, None)
                )
            state.gateway_of_last_resort = hops[0][0] if hops else None

        for network in sorted(set(advertised) | set(connected), key=_network_key):
            if network in connected:
                port, address = connected[network]
                host = f"{address.ip}/32"
                if port.kind is InterfaceKind.LOOPBACK:
                    routes.append(_connected(host, RouteProtocol.CONNECTED, port.name))
                else:
                    routes.append(_connected(str(network), RouteProtocol.CONNECTED, port.name))
                    routes.append(_connected(host, RouteProtocol.LOCAL, port.name))
                continue
            owners = {o for o in advertised[network] if o in distance}
            if not owners:
                continue
            best = min(distance[o] for o in owners)
            nearest = {o for o in owners if distance[o] == best}
            for peer_ip, interface in _next_hops(state.name, nearest, distance, adjacent):
                routes.append(
                    pm.Route(
                        str(network), RouteProtocol.OSPF, peer_ip, interface, 110, best + 1, None
                    )
                )
        state.routes = routes


def _connected(prefix: str, protocol: RouteProtocol, interface: str) -> pm.Route:
    return pm.Route(prefix, protocol, None, interface, None, None, None)


def _network_key(network: ipaddress.IPv4Network) -> tuple[int, int]:
    return (int(network.network_address), network.prefixlen)


def _hop_distances(start: str, adjacent: dict[str, list[tuple[str, Port, Port]]]) -> dict[str, int]:
    distance = {start: 0}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for peer, _, _ in adjacent.get(node, []):
            if peer not in distance:
                distance[peer] = distance[node] + 1
                queue.append(peer)
    return distance


def _next_hops(
    start: str,
    targets: set[str],
    distance: dict[str, int],
    adjacent: dict[str, list[tuple[str, Port, Port]]],
) -> list[tuple[str, str]]:
    """(next-hop IP, local interface) of every first hop on a shortest path to ``targets``."""
    best = min(distance[t] for t in targets)
    hops = []
    for peer, port, peer_port in adjacent.get(start, []):
        to_target = _hop_distances(peer, adjacent)
        if any(to_target.get(t, 1 << 30) == best - 1 for t in targets) and peer_port.address:
            hops.append((str(peer_port.address.ip), port.name))
    return sorted(set(hops), key=lambda hop: ipaddress.IPv4Address(hop[0]), reverse=True)


# --- CDP / LLDP -------------------------------------------------------------------------------


def advertised_ip(lab: Lab, device: DeviceState, toward: DeviceState) -> str:
    """The address ``device`` puts in CDP/LLDP for ``toward``: its SVI in ``toward``'s
    management VLAN if it has one (a device with two management SVIs advertises different
    addresses to different neighbours), otherwise its management address."""
    vlan = lab.topology.vlan_of(toward.device.mgmt_ip)
    if vlan is not None:
        svi = device.svi(vlan.id)
        if svi is not None and svi.address is not None:
            return str(svi.address.ip)
    return str(device.device.mgmt_ip)


def device_id(lab: Lab, state: DeviceState) -> str:
    if state.kind is Kind.AP or state.device.external:
        return state.name
    return f"{state.name}.{lab.topology.domain}"


def platform(state: DeviceState) -> str:
    return f"cisco {state.device.model}"


def _neighbors(lab: Lab) -> None:
    for state in lab.served():
        for port in state.ports.values():
            if port.peer is None:
                continue
            peer = lab.devices[port.peer[0]]
            remote_port = port.peer[1]
            address = advertised_ip(lab, peer, state)
            state.cdp.append(
                pm.Neighbor(
                    protocol=NeighborProtocol.CDP,
                    local_interface=port.name,
                    remote_name=device_id(lab, peer),
                    remote_mgmt_ip=address,
                    remote_port=remote_port,
                    remote_platform=platform(peer),
                    remote_capabilities=_CDP_CAPABILITIES[peer.kind],
                )
            )
            if peer.kind in _LLDP_CAPABILITIES and not peer.device.external:
                state.lldp.append(
                    pm.Neighbor(
                        protocol=NeighborProtocol.LLDP,
                        local_interface=port.name,
                        remote_name=device_id(lab, peer),
                        remote_mgmt_ip=address,
                        remote_port=abbreviate(remote_port),
                        remote_platform=software_line(peer),
                        remote_capabilities=_LLDP_CAPABILITIES[peer.kind],
                    )
                )


_SOFTWARE = {
    "router": "Cisco IOS Software [Cupertino], ISR Software (X86_64_LINUX_IOSD-UNIVERSALK9-M)",
    "ios": "Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M)",
    "iosxe": "Cisco IOS Software [Dublin], Catalyst L3 Switch Software (CAT9K_IOSXE)",
}


def software_line(state: DeviceState) -> str:
    """The "Cisco IOS Software, ..., Version X" line of show version (and CDP/LLDP)."""
    family = "router" if state.kind is Kind.ROUTER else state.device.os
    return f"{_SOFTWARE[family]}, Version {state.device.version}, RELEASE SOFTWARE (fc1)"


# --- expected parser results ------------------------------------------------------------------


def interface_statuses(state: DeviceState) -> list[pm.InterfaceStatus]:
    statuses = []
    for port in ordered_ports(state):
        physical = port.kind in (InterfaceKind.PHYSICAL, InterfaceKind.PORT_CHANNEL)
        statuses.append(
            pm.InterfaceStatus(
                name=port.name,
                kind=port.kind,
                admin_up=True,
                oper_up=True,
                err_disabled=False,
                description=port.description,
                mac=port.mac,
                mtu=1514 if port.kind is InterfaceKind.LOOPBACK else 1500,
                speed_mbps=port.speed_mbps if physical else None,
                duplex=Duplex.FULL if physical else None,
                address=str(port.address) if port.address else None,
                in_errors=0,
                crc_errors=0,
                late_collisions=0 if physical else None,
            )
        )
    return statuses


def ordered_ports(state: DeviceState) -> list[Port]:
    order = {
        InterfaceKind.SVI: 0,
        InterfaceKind.PHYSICAL: 1,
        InterfaceKind.PORT_CHANNEL: 2,
        InterfaceKind.LOOPBACK: 3,
    }
    return sorted(state.ports.values(), key=lambda p: (order.get(p.kind, 4), p.number))


def switchports(state: DeviceState) -> list[pm.Switchport]:
    result = []
    for port in ordered_ports(state):
        if port.mode is None:
            continue
        if port.mode is SwitchportMode.TRUNK:
            result.append(
                pm.Switchport(port.name, port.mode, None, port.native_vlan, port.allowed_vlans)
            )
        elif port.mode is SwitchportMode.ROUTED:
            result.append(pm.Switchport(port.name, port.mode, None, None, None))
        else:
            result.append(pm.Switchport(port.name, port.mode, port.access_vlan, None, None))
    return result


def etherchannels(state: DeviceState) -> list[pm.EtherChannel]:
    channels = sorted({p.channel for p in state.ports.values() if p.channel is not None})
    return [
        pm.EtherChannel(
            port_channel=f"Port-channel{channel}",
            protocol="LACP",
            members=tuple((p.name, "P") for p in ordered_ports(state) if p.channel == channel),
        )
        for channel in channels
    ]


def vlans(lab: Lab, state: DeviceState) -> list[pm.Vlan]:
    result = [pm.Vlan(1, "default", VlanStatus.ACTIVE, ())]
    for vlan in lab.topology.vlans:
        ports = tuple(
            p.name
            for p in ordered_ports(state)
            if p.mode is SwitchportMode.ACCESS and p.access_vlan == vlan.id
        )
        result.append(pm.Vlan(vlan.id, vlan.name, VlanStatus.ACTIVE, ports))
    result.extend(pm.Vlan(v, name, VlanStatus.UNSUPPORTED, ()) for v, name in DEFAULT_VLANS)
    return result


def ip_interfaces(state: DeviceState) -> list[pm.IpInterface]:
    return [
        pm.IpInterface(
            port.name, str(port.address.ip) if port.address else None, admin_up=True, oper_up=True
        )
        for port in ordered_ports(state)
    ]


def inventory(state: DeviceState) -> list[pm.InventoryItem]:
    if state.kind is Kind.ROUTER:
        return [
            pm.InventoryItem(
                name="Chassis",
                description=f"Cisco {state.device.model.split('/')[0]} Chassis",
                pid=state.device.model,
                serial=state.device.serials[0],
                stack_member=None,
            )
        ]
    return [
        pm.InventoryItem(
            name=f"Switch {member}",
            description=state.device.model,
            pid=state.device.model,
            serial=serial,
            stack_member=member,
        )
        for member, serial in enumerate(state.device.serials, start=1)
    ]


def facts(state: DeviceState) -> pm.Facts:
    return pm.Facts(
        hostname=state.name,
        os_family=state.os_family,
        os_version=state.device.version,
        model=state.device.model,
        serials=tuple(state.device.serials),
        uptime=UPTIME,
    )


def _expected(lab: Lab, state: DeviceState) -> dict[str, object]:
    expected: dict[str, object] = {
        "show version": facts(state),
        "show inventory": inventory(state),
        "show cdp neighbors detail": state.cdp,
        "show lldp neighbors detail": state.lldp,
        "show interfaces": interface_statuses(state),
        "show ip interface brief": ip_interfaces(state),
        "show ip arp": state.arps,
    }
    if state.is_switch:
        expected |= {
            "show interfaces switchport": switchports(state),
            "show etherchannel summary": etherchannels(state),
            "show vlan brief": vlans(lab, state),
            "show mac address-table": state.macs,
            "show spanning-tree": state.stp,
        }
    if state.is_l3:
        expected |= {
            "show ip route": state.routes,
            "show standby brief": state.hsrp,
            "show ip ospf neighbor": state.ospf_neighbors,
            "show ip ospf interface brief": state.ospf_interfaces,
        }
    else:
        expected["show ip route"] = []  # "Default gateway is ..." (ip routing disabled)
    return expected
