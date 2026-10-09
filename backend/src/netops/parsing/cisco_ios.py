"""Parsers for Cisco IOS / IOS-XE ``show`` commands (TextFSM via ntc-templates).

Each parser takes the raw output of one command and returns vendor-neutral models
(netops.parsing.models). IOS-XE output uses the same templates as IOS.
"""

import io
import ipaddress
import re
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

import textfsm
from ntc_templates.parse import parse_output

from netops.core.ifname import interface_kind, normalize
from netops.db.enums import (
    HsrpState,
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
from netops.parsing import normalize as canon
from netops.parsing.errors import check_output
from netops.parsing.models import (
    ArpEntry,
    EtherChannel,
    Facts,
    HsrpGroup,
    InterfaceStatus,
    InventoryItem,
    IpInterface,
    MacEntry,
    Neighbor,
    OspfInterface,
    OspfNeighbor,
    Route,
    SpanningTree,
    StpInstance,
    StpPort,
    Switchport,
    Vlan,
)

_TEMPLATES = Path(__file__).parent / "templates"
_PLATFORM = "cisco_ios"


class ParseError(Exception):
    """Output was accepted by the device but could not be understood."""


Row = dict[str, Any]


def _ntc(command: str, raw: str) -> list[Row]:
    rows: list[Row] = parse_output(platform=_PLATFORM, command=command, data=raw)
    return rows


@cache
def _template_source(name: str) -> str:
    return (_TEMPLATES / f"{name}.textfsm").read_text()


def _custom(name: str, raw: str) -> list[Row]:
    """Run one of this package's own TextFSM templates (gaps in ntc-templates)."""
    fsm = textfsm.TextFSM(io.StringIO(_template_source(name)))
    header = [h.lower() for h in fsm.header]
    return [dict(zip(header, row, strict=True)) for row in fsm.ParseText(raw)]


def _interface(value: str | None) -> str | None:
    """Canonical name, or None for things that are not interfaces (CPU, Drop, '-', '')."""
    if not value or not any(ch.isdigit() for ch in value):
        return None
    return normalize(value)


# --- Facts ----------------------------------------------------------------------------------


def parse_show_version(raw: str) -> Facts:
    rows = _ntc("show version", raw)
    if not rows:
        raise ParseError("show version: no version information found")
    row = rows[0]
    serials = tuple(dict.fromkeys(s.strip().upper() for s in row["serial"] if s.strip()))
    hardware = [h for h in row["hardware"] if h]
    is_xe = re.search(r"IOS[ -]XE", raw, re.IGNORECASE) is not None
    return Facts(
        hostname=row["hostname"] or None,
        os_family=OsFamily.IOSXE if is_xe else OsFamily.IOS,
        os_version=row["version"] or None,
        model=hardware[0] if hardware else None,
        serials=serials,
        uptime=row["uptime"] or None,
    )


_STACK_MEMBER = re.compile(r"^(?:Switch|Chassis)\s*(\d+)$", re.IGNORECASE)


def parse_show_inventory(raw: str) -> list[InventoryItem]:
    items = []
    for row in _ntc("show inventory", raw):
        member = _STACK_MEMBER.match(row["name"].strip())
        items.append(
            InventoryItem(
                name=row["name"].strip(),
                description=row["descr"].strip(),
                pid=row["pid"].strip() or None,
                serial=row["sn"].strip().upper() or None,
                stack_member=int(member.group(1)) if member else None,
            )
        )
    return items


# --- Neighbours -----------------------------------------------------------------------------

_LLDP_CAPABILITIES = {
    "B": "bridge",
    "C": "docsis",
    "O": "other",
    "P": "repeater",
    "R": "router",
    "S": "station",
    "T": "telephone",
    "W": "wlan-access-point",
}


def parse_cdp_neighbors_detail(raw: str) -> list[Neighbor]:
    if not check_output("show cdp neighbors detail", raw):
        return []
    neighbors = []
    for row in _ntc("show cdp neighbors detail", raw):
        local = _interface(row["local_interface"])
        if local is None:
            continue
        neighbors.append(
            Neighbor(
                protocol=NeighborProtocol.CDP,
                local_interface=local,
                remote_name=row["neighbor_name"] or None,
                remote_mgmt_ip=canon.ip(row["mgmt_address"]),
                remote_port=row["neighbor_interface"] or None,
                remote_platform=row["platform"] or None,
                remote_capabilities=tuple(row["capabilities"].split()),
            )
        )
    return neighbors


def parse_lldp_neighbors_detail(raw: str) -> list[Neighbor]:
    if not check_output("show lldp neighbors detail", raw):
        return []
    neighbors = []
    for row in _ntc("show lldp neighbors detail", raw):
        local = _interface(row["local_interface"])
        if local is None:
            continue  # older IOS releases do not print the local interface
        codes = [c.strip() for c in row["capabilities"].split(",") if c.strip()]
        neighbors.append(
            Neighbor(
                protocol=NeighborProtocol.LLDP,
                local_interface=local,
                remote_name=row["neighbor_name"] or None,
                remote_mgmt_ip=canon.ip(row["mgmt_address"]),
                remote_port=row["neighbor_port_id"] or row["neighbor_interface"] or None,
                remote_platform=row["platform"] or row["neighbor_description"] or None,
                remote_capabilities=tuple(_LLDP_CAPABILITIES.get(c, c.lower()) for c in codes),
            )
        )
    return neighbors


# --- Interfaces -----------------------------------------------------------------------------


def parse_show_interfaces(raw: str) -> list[InterfaceStatus]:
    late = {
        normalize(row["interface"]): canon.integer(row["late_collisions"])
        for row in _custom("cisco_ios_show_interfaces_late_collisions", raw)
    }
    interfaces = []
    for row in _ntc("show interfaces", raw):
        name = normalize(row["interface"])
        link, protocol = row["link_status"].lower(), row["protocol_status"].lower()
        interfaces.append(
            InterfaceStatus(
                name=name,
                kind=interface_kind(name),
                admin_up="administratively" not in link and "(disabled)" not in protocol,
                oper_up=protocol.startswith("up"),
                err_disabled="err-disabled" in protocol or "err-disabled" in link,
                description=row["description"].strip() or None,
                mac=canon.mac(row["mac_address"]),
                mtu=canon.integer(row["mtu"]),
                speed_mbps=canon.speed_mbps(row["speed"]),
                duplex=canon.duplex(row["duplex"]),
                address=canon.ip_with_prefix(row["ip_address"], row["prefix_length"]),
                in_errors=canon.integer(row["input_errors"]),
                crc_errors=canon.integer(row["crc"]),
                late_collisions=late.get(name),
            )
        )
    return interfaces


_ADMIN_MODES = {"static access": SwitchportMode.ACCESS, "trunk": SwitchportMode.TRUNK}


def parse_interfaces_switchport(raw: str) -> list[Switchport]:
    ports = []
    for row in _ntc("show interfaces switchport", raw):
        name = normalize(row["interface"])
        if row["switchport"].lower() == "disabled":
            ports.append(Switchport(name, SwitchportMode.ROUTED, None, None, None))
            continue
        # Operational mode; while the port is down IOS prints "down", so fall back to a
        # static administrative mode. Negotiating (dynamic) ports stay unknown.
        operational = row["mode"].lower()
        mode = _ADMIN_MODES.get(operational) or _ADMIN_MODES.get(
            row["admin_mode"].lower(), SwitchportMode.UNKNOWN
        )
        if mode is SwitchportMode.TRUNK:
            ports.append(
                Switchport(
                    name,
                    mode,
                    access_vlan=None,
                    native_vlan=canon.integer(row["native_vlan"]),
                    allowed_vlans=canon.vlan_list(row["trunking_vlans"]),
                )
            )
        else:
            ports.append(Switchport(name, mode, canon.integer(row["access_vlan"]), None, None))
    return ports


def parse_etherchannel_summary(raw: str) -> list[EtherChannel]:
    channels = []
    for row in _ntc("show etherchannel summary", raw):
        members = tuple(
            (normalize(member), status)
            for member, status in zip(
                row["member_interface"], row["member_interface_status"], strict=False
            )
        )
        channels.append(
            EtherChannel(
                port_channel=normalize(row["bundle_name"]),
                protocol=row["bundle_protocol"] or None,
                members=members,
            )
        )
    return channels


def parse_ip_interface_brief(raw: str) -> list[IpInterface]:
    return [
        IpInterface(
            interface=normalize(row["interface"]),
            address=canon.ip(row["ip_address"]),
            admin_up="administratively" not in row["status"].lower(),
            oper_up=row["proto"].lower() == "up",
        )
        for row in _ntc("show ip interface brief", raw)
    ]


# --- VLANs, MAC and ARP tables -----------------------------------------------------------------


def _vlan_status(text: str) -> VlanStatus:
    text = text.lower()
    if "lshut" in text:
        return VlanStatus.SHUTDOWN
    if "unsup" in text:
        return VlanStatus.UNSUPPORTED
    if text.startswith("sus"):
        return VlanStatus.SUSPENDED
    if text == "active":
        return VlanStatus.ACTIVE
    return VlanStatus.UNKNOWN


def parse_vlans(raw: str) -> list[Vlan]:
    """``show vlan brief`` (and ``show vlan``)."""
    return [
        Vlan(
            vlan_id=int(row["vlan_id"]),
            name=row["vlan_name"] or None,
            status=_vlan_status(row["status"]),
            ports=tuple(normalize(p) for p in row["interfaces"] if p),
        )
        for row in _ntc("show vlan", raw)
        if row["vlan_id"].isdigit() and 1 <= int(row["vlan_id"]) <= 4094
    ]


def _mac_type(text: str) -> MacEntryType:
    text = text.lower()
    if text == "dynamic":
        return MacEntryType.DYNAMIC
    if text == "static":
        return MacEntryType.STATIC
    return MacEntryType.OTHER


def parse_mac_address_table(raw: str) -> list[MacEntry]:
    entries: dict[tuple[int, str], MacEntry] = {}
    for row in _ntc("show mac address-table", raw):
        address = canon.mac(row["destination_address"])
        if not row["vlan_id"].isdigit() or address is None:
            continue  # "All" VLAN entries are the switch's own CPU addresses
        ports = [p for p in (_interface(port) for port in row["destination_port"]) if p]
        entry = MacEntry(
            vlan_id=int(row["vlan_id"]),
            mac=address,
            interface=ports[0] if ports else None,
            entry_type=_mac_type(row["type"]),
        )
        entries.setdefault((entry.vlan_id, entry.mac), entry)
    return list(entries.values())


def parse_ip_arp(raw: str) -> list[ArpEntry]:
    entries = []
    for row in _ntc("show ip arp", raw):
        address, mac, interface = (
            canon.ip(row["ip_address"]),
            canon.mac(row["mac_address"]),
            _interface(row["interface"]),
        )
        if address is None or mac is None or interface is None:
            continue  # incomplete entries
        entries.append(ArpEntry(ip=address, mac=mac, interface=interface, vrf=None))
    return entries


# --- Routing --------------------------------------------------------------------------------

_ROUTE_PROTOCOLS = {
    "C": RouteProtocol.CONNECTED,
    "L": RouteProtocol.LOCAL,
    "S": RouteProtocol.STATIC,
    "O": RouteProtocol.OSPF,
}


def parse_ip_route(raw: str) -> list[Route]:
    routes = []
    for row in _ntc("show ip route", raw):
        prefix = canon.network(row["network"], row["prefix_length"])
        if prefix is None:
            continue
        code = row["protocol"].rstrip("*").strip()
        routes.append(
            Route(
                prefix=prefix,
                protocol=_ROUTE_PROTOCOLS.get(code, RouteProtocol.OTHER),
                next_hop=canon.ip(row["nexthop_ip"]),
                interface=_interface(row["nexthop_if"]),
                admin_distance=canon.integer(row["distance"]),
                metric=canon.integer(row["metric"]),
                vrf=row["vrf"] or None,
            )
        )
    return routes


_STP_ROLES = {
    "root": StpPortRole.ROOT,
    "desg": StpPortRole.DESIGNATED,
    "altn": StpPortRole.ALTERNATE,
    "back": StpPortRole.BACKUP,
    "disa": StpPortRole.DISABLED,
    "dis": StpPortRole.DISABLED,
}
_STP_STATES = {
    "fwd": StpPortState.FORWARDING,
    "blk": StpPortState.BLOCKING,
    "lrn": StpPortState.LEARNING,
    "lis": StpPortState.LISTENING,
    "dis": StpPortState.DISABLED,
    "bkn": StpPortState.BROKEN,
}


def parse_spanning_tree(raw: str) -> SpanningTree:
    instances = tuple(
        StpInstance(
            vlan_id=int(row["vlan_id"]),
            root_bridge_id=f"{row['root_priority']} {row['root_address'].lower()}",
            root_cost=canon.integer(row["root_cost"]) or 0,
            root_interface=_interface(row["root_port"]),
            is_root=bool(row["is_root"]),
        )
        for row in _custom("cisco_ios_show_spanning-tree_root", raw)
        if row["root_priority"] and row["root_address"]
    )
    ports = []
    for row in _ntc("show spanning-tree", raw):
        role = _STP_ROLES.get(row["role"].lower())
        state = _STP_STATES.get(row["status"].rstrip("*").lower())
        if role is None or state is None:
            continue  # e.g. MST boundary roles, which PVST campus designs do not use
        ports.append(
            StpPort(
                vlan_id=int(row["vlan_id"]),
                interface=normalize(row["interface"]),
                role=role,
                state=state,
                cost=canon.integer(row["cost"]) or 0,
            )
        )
    return SpanningTree(instances=instances, ports=tuple(ports))


_HSRP_STATES = {state.value: state for state in HsrpState} | {"initial": HsrpState.INIT}


def parse_standby_brief(raw: str) -> list[HsrpGroup]:
    groups = []
    for row in _ntc("show standby brief", raw):
        virtual_ip = canon.ip(row["virtual_ip_address"])
        state = _HSRP_STATES.get(row["state"].lower())
        if virtual_ip is None or state is None:
            continue
        groups.append(
            HsrpGroup(
                interface=normalize(row["interface"]),
                group=int(row["group"]),
                priority=int(row["priority"]),
                preempt=row["preempt"].upper() == "P",
                state=state,
                virtual_ip=virtual_ip,
                active_router=canon.ip(row["active"]),
                active_is_local=row["active"].lower() == "local",
                standby_router=canon.ip(row["standby"]),
                standby_is_local=row["standby"].lower() == "local",
            )
        )
    return groups


_OSPF_STATES = {state.value: state for state in OspfNeighborState}


def parse_ospf_neighbors(raw: str) -> list[OspfNeighbor]:
    neighbors = []
    for row in _ntc("show ip ospf neighbor", raw):
        state_text, _, role = row["state"].partition("/")
        state = _OSPF_STATES.get(state_text.strip().lower())
        router_id, address = canon.ip(row["neighbor_id"]), canon.ip(row["ip_address"])
        interface = _interface(row["interface"])
        if state is None or router_id is None or address is None or interface is None:
            continue
        role = role.strip()
        neighbors.append(
            OspfNeighbor(
                router_id=router_id,
                address=address,
                interface=interface,
                state=state,
                role=role if role and role != "-" else None,
            )
        )
    return neighbors


def _ospf_area(value: str) -> int | None:
    value = value.strip()
    if value.isdigit():
        return int(value)
    try:
        return int(ipaddress.IPv4Address(value))
    except ValueError:
        return None


def parse_ospf_interface_brief(raw: str) -> list[OspfInterface]:
    interfaces = []
    for row in _ntc("show ip ospf interface brief", raw):
        area = _ospf_area(row["area"])
        if area is None:
            continue
        interfaces.append(
            OspfInterface(
                interface=normalize(row["interface"]),
                process=row["process"],
                area=area,
                address=canon.ip_with_prefix(row["ip_address"], row["prefix_length"]),
                cost=canon.integer(row["cost"]),
                state=row["state"],
            )
        )
    return interfaces


# Command (exactly as sent to the device) -> parser.
PARSERS: dict[str, Callable[[str], object]] = {
    "show version": parse_show_version,
    "show inventory": parse_show_inventory,
    "show cdp neighbors detail": parse_cdp_neighbors_detail,
    "show lldp neighbors detail": parse_lldp_neighbors_detail,
    "show interfaces": parse_show_interfaces,
    "show interfaces switchport": parse_interfaces_switchport,
    "show etherchannel summary": parse_etherchannel_summary,
    "show ip interface brief": parse_ip_interface_brief,
    "show vlan brief": parse_vlans,
    "show mac address-table": parse_mac_address_table,
    "show ip arp": parse_ip_arp,
    "show ip route": parse_ip_route,
    "show spanning-tree": parse_spanning_tree,
    "show standby brief": parse_standby_brief,
    "show ip ospf neighbor": parse_ospf_neighbors,
    "show ip ospf interface brief": parse_ospf_interface_brief,
}


def parse(command: str, raw: str) -> object:
    """Parse one command's output; raises CommandError for CLI errors, ParseError if unknown."""
    check_output(command, raw)
    try:
        parser = PARSERS[command]
    except KeyError:
        raise ParseError(f"no parser for {command!r}") from None
    return parser(raw)
