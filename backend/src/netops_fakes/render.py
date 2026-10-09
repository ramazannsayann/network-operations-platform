"""Render a device's derived state (netops_fakes.lab) as IOS / IOS-XE CLI output.

Formats follow the real outputs in lab/fixtures. Commands a device type does not have
(switching commands on the router, HSRP and OSPF on L2 switches) are not rendered, so the
fake device answers them with "% Invalid input detected", like IOS.
"""

import ipaddress

from netops.core.ifname import abbreviate
from netops.db.enums import (
    HsrpState,
    InterfaceKind,
    OspfNeighborState,
    RouteProtocol,
    StpPortRole,
    StpPortState,
    SwitchportMode,
)
from netops.parsing import models as pm
from netops_fakes.lab import (
    UPTIME,
    DeviceState,
    Lab,
    Port,
    device_id,
    dotted,
    etherchannels,
    inventory,
    ordered_ports,
    platform,
    software_line,
    vlans,
)
from netops_fakes.topology import Kind

_SUPPORT = (
    "Technical Support: http://www.cisco.com/techsupport\n"
    "Copyright (c) 1986-2024 by Cisco Systems, Inc."
)


def render(lab: Lab, state: DeviceState) -> dict[str, str]:
    """Command -> CLI output for every command this device supports."""
    outputs = {
        "show version": show_version(state),
        "show inventory": show_inventory(state),
        "show cdp neighbors detail": show_cdp(lab, state),
        "show lldp neighbors detail": show_lldp(lab, state),
        "show interfaces": show_interfaces(state),
        "show ip interface brief": show_ip_interface_brief(state),
        "show ip arp": show_ip_arp(state),
        "show ip route": show_ip_route(state),
    }
    if state.is_switch:
        outputs |= {
            "show interfaces switchport": show_switchport(lab, state),
            "show etherchannel summary": show_etherchannel(state),
            "show vlan brief": show_vlan_brief(lab, state),
            "show mac address-table": show_mac_table(state),
            "show spanning-tree": show_spanning_tree(state),
        }
    if state.is_l3:
        outputs |= {
            "show standby brief": show_standby_brief(state),
            "show ip ospf neighbor": show_ospf_neighbors(state),
            "show ip ospf interface brief": show_ospf_interfaces(state),
        }
    return outputs


# --- show version / inventory -----------------------------------------------------------------


def show_version(state: DeviceState) -> str:
    device = state.device
    serial = device.serials[0]
    if state.kind is Kind.ROUTER:
        return f"""Cisco IOS XE Software, Version {device.version}
{software_line(state)}
{_SUPPORT}
Compiled Fri 20-Oct-23 10:44 by mcpre


ROM: IOS-XE ROMMON

{device.name} uptime is {UPTIME}
Uptime for this control processor is {UPTIME}
System returned to ROM by Reload Command
System image file is "bootflash:isr4300-universalk9.{device.version}.SPA.bin"
Last reload reason: Reload Command


cisco {device.model} (1RU) processor with 1795979K/6147K bytes of memory.
Processor board ID {serial}
Router operating mode: Autonomous
3 Gigabit Ethernet interfaces
32768K bytes of non-volatile configuration memory.
4194304K bytes of physical memory.

Configuration register is 0x2102
"""
    if device.os == "ios":
        return f"""{software_line(state)}
{_SUPPORT}
Compiled Mon 22-Apr-24 14:52 by mcpre

ROM: Bootstrap program is C2960X boot loader
BOOTLDR: C2960X Boot Loader (C2960X-HBOOT-M) Version 15.2(7r)E2, RELEASE SOFTWARE (fc1)

{device.name} uptime is {UPTIME}
System returned to ROM by power-on
System image file is "flash:c2960x-universalk9-mz.bin"
Last reload reason: power-on


cisco {device.model} (APM86XXX) processor (revision A0) with 524288K bytes of memory.
Processor board ID {serial}
Last reset from power-on
1 Virtual Ethernet interface
52 Gigabit Ethernet interfaces
The password-recovery mechanism is enabled.

512K bytes of flash-simulated non-volatile configuration memory.
Base ethernet MAC Address       : {state.bridge_mac}
Motherboard assembly number     : 73-15723-08
Model number                    : {device.model}
System serial number            : {serial}

Switch Ports Model                     SW Version            SW Image
------ ----- -----                     ----------            ----------
*    1 52    {device.model:<25} {device.version:<21} C2960X-UNIVERSALK9-M

Configuration register is 0xF
"""
    members = "".join(
        f"""

Switch {number:02d}
---------
Switch uptime                      : {UPTIME}

Base Ethernet MAC Address          : {state.bridge_mac}
Model Number                       : {device.model}
System Serial Number               : {member_serial}"""
        for number, member_serial in enumerate(device.serials[1:], start=2)
    )
    table = "\n".join(
        f"{'*' if number == 1 else ' '}    {number} 65    {device.model:<18} "
        f"{device.version:<17} CAT9K_IOSXE           INSTALL"
        for number in range(1, len(device.serials) + 1)
    )
    return f"""Cisco IOS XE Software, Version {device.version}
{software_line(state)}
{_SUPPORT}
Compiled Thu 12-Sep-24 10:11 by mcpre


ROM: IOS-XE ROMMON
BOOTLDR: System Bootstrap, Version 17.11.1r, RELEASE SOFTWARE (P)

{device.name} uptime is {UPTIME}
Uptime for this control processor is {UPTIME}
System returned to ROM by Reload Command
System image file is "flash:packages.conf"
Last reload reason: Reload Command


cisco {device.model} (X86) processor with 1331521K/6147K bytes of memory.
Processor board ID {serial}
2048K bytes of non-volatile configuration memory.
8388608K bytes of physical memory.

Base Ethernet MAC Address          : {state.bridge_mac}
Model Number                       : {device.model}
System Serial Number               : {serial}


Switch Ports Model              SW Version        SW Image              Mode
------ ----- -----              ----------        ----------            ----
{table}{members}

Configuration register is 0x102
"""


def show_inventory(state: DeviceState) -> str:
    blocks = [
        f'NAME: "{item.name}", DESCR: "{item.description}"\n'
        f"PID: {item.pid or '':<17} , VID: V02  , SN: {item.serial or ''}\n"
        for item in inventory(state)
    ]
    return "\n".join(blocks) + "\n"


# --- neighbours -----------------------------------------------------------------------------


def _peer_software(peer: DeviceState) -> str:
    if peer.kind is Kind.AP:
        return f"Cisco AP Software, {peer.device.model} Version: {peer.device.version}"
    return software_line(peer)


def show_cdp(lab: Lab, state: DeviceState) -> str:
    blocks = []
    for neighbor in state.cdp:
        peer = _peer_by_id(lab, neighbor.remote_name)
        blocks.append(
            f"""-------------------------
Device ID: {neighbor.remote_name}
Entry address(es):
  IP address: {neighbor.remote_mgmt_ip}
Platform: {platform(peer)},  Capabilities: {" ".join(neighbor.remote_capabilities)}
Interface: {neighbor.local_interface},  Port ID (outgoing port): {neighbor.remote_port}
Holdtime : 151 sec

Version :
{_peer_software(peer)}
{_SUPPORT}

advertisement version: 2
Native VLAN: 1
Duplex: full
Management address(es):
  IP address: {neighbor.remote_mgmt_ip}

"""
        )
    return "".join(blocks) + f"\nTotal cdp entries displayed : {len(blocks)}\n"


_LLDP_CODES = {"bridge": "B", "router": "R"}


def show_lldp(lab: Lab, state: DeviceState) -> str:
    blocks = []
    for neighbor in state.lldp:
        peer = _peer_by_id(lab, neighbor.remote_name)
        codes = ",".join(_LLDP_CODES[c] for c in neighbor.remote_capabilities)
        remote_port = next(
            p.peer[1]
            for p in state.ports.values()
            if p.name == neighbor.local_interface and p.peer is not None
        )
        blocks.append(
            f"""------------------------------------------------
Local Intf: {abbreviate(neighbor.local_interface)}
Chassis id: {dotted(peer.bridge_mac)}
Port id: {neighbor.remote_port}
Port Description: {remote_port}
System Name: {neighbor.remote_name}

System Description:
{neighbor.remote_platform}
{_SUPPORT}

Time remaining: 104 seconds
System Capabilities: {codes}
Enabled Capabilities: {codes}
Management Addresses:
    IP: {neighbor.remote_mgmt_ip}
Auto Negotiation - not supported
Physical media capabilities - not advertised
Media Attachment Unit type - not advertised
Vlan ID: - not advertised

"""
        )
    return "".join(blocks) + f"\nTotal entries displayed: {len(blocks)}\n"


def _peer_by_id(lab: Lab, remote_name: str | None) -> DeviceState:
    return next(d for d in lab.devices.values() if device_id(lab, d) == remote_name)


# --- interfaces -------------------------------------------------------------------------------


def _speed_text(speed: int) -> str:
    return f"{speed // 1000}Gb/s" if speed >= 10_000 and speed % 1000 == 0 else f"{speed}Mb/s"


def _hardware(state: DeviceState, port: Port) -> str:
    if port.kind is InterfaceKind.PORT_CHANNEL:
        return "EtherChannel"
    if state.kind is Kind.ROUTER:
        return "ISR4331-3x1GE"
    return "Ten Gigabit Ethernet" if port.name.startswith("Ten") else "Gigabit Ethernet"


def _counters(physical: bool) -> str:
    collisions = "0 collisions, " if physical else ""
    late = "     0 babbles, 0 late collision, 0 deferred\n" if physical else ""
    return f"""     1203433 packets input, 182349322 bytes, 0 no buffer
     Received 12384 broadcasts (8231 multicasts)
     0 runts, 0 giants, 0 throttles
     0 input errors, 0 CRC, 0 frame, 0 overrun, 0 ignored
     4823311 packets output, 1923312349 bytes, 0 underruns
     Output 23111 broadcasts (0 multicasts)
     0 output errors, {collisions}1 interface resets
     0 unknown protocol drops
{late}     0 output buffer failures, 0 output buffers swapped out
"""


def show_interfaces(state: DeviceState) -> str:
    blocks = []
    for port in ordered_ports(state):
        address_text = f"{dotted(port.mac or '')} (bia {dotted(port.mac or '')})"
        description = f"  Description: {port.description}\n" if port.description else ""
        address = f"  Internet address is {port.address}\n" if port.address else ""
        if port.kind is InterfaceKind.LOOPBACK:
            blocks.append(
                f"""{port.name} is up, line protocol is up
  Hardware is Loopback
{description}{address}  MTU 1514 bytes, BW 8000000 Kbit/sec, DLY 5000 usec,
     reliability 255/255, txload 1/255, rxload 1/255
  Encapsulation LOOPBACK, loopback not set
  Keepalive set (10 sec)
  Last input never, output never, output hang never
{_counters(False)}"""
            )
        elif port.kind is InterfaceKind.SVI:
            blocks.append(
                f"""{port.name} is up, line protocol is up , Autostate Enabled
  Hardware is Ethernet SVI, address is {address_text}
{description}{address}  MTU 1500 bytes, BW 1000000 Kbit/sec, DLY 10 usec,
     reliability 255/255, txload 1/255, rxload 1/255
  Encapsulation ARPA, loopback not set
  Keepalive not supported
  ARP type: ARPA, ARP Timeout 04:00:00
  Last input 00:00:00, output 00:00:00, output hang never
{_counters(False)}"""
            )
        else:
            speed = port.speed_mbps or 1000
            link_type, media, members = "", "10/100/1000BaseTX", ""
            if port.kind is InterfaceKind.PORT_CHANNEL:
                channel = int(port.name.removeprefix("Port-channel"))
                names = " ".join(
                    abbreviate(p.name) for p in ordered_ports(state) if p.channel == channel
                )
                link_type, media = ", link type is auto", "N/A"
                members = f"  Members in this channel: {names} \n"
            protocol = "up (connected)" if state.is_switch else "up"
            blocks.append(
                f"""{port.name} is up, line protocol is {protocol}
  Hardware is {_hardware(state, port)}, address is {address_text}
{description}{address}  MTU 1500 bytes, BW {speed * 1000} Kbit/sec, DLY 10 usec,
     reliability 255/255, txload 1/255, rxload 1/255
  Encapsulation ARPA, loopback not set
  Keepalive set (10 sec)
  Full-duplex, {_speed_text(speed)}{link_type}, media type is {media}
  input flow-control is on, output flow-control is unsupported
{members}  ARP type: ARPA, ARP Timeout 04:00:00
  Last input 00:00:01, output 00:00:00, output hang never
{_counters(True)}"""
            )
    return "".join(blocks)


def show_ip_interface_brief(state: DeviceState) -> str:
    lines = ["Interface              IP-Address      OK? Method Status                Protocol"]
    for port in ordered_ports(state):
        ip = str(port.address.ip) if port.address else "unassigned"
        method = "NVRAM" if port.address else "unset"
        lines.append(f"{port.name:<22} {ip:<15} YES {method:<6} up                    up      ")
    return "\n".join(lines) + "\n"


def vlan_list_text(vlans: tuple[int, ...]) -> str:
    """(10, 20, 98, 99) -> '10,20,98-99'."""
    parts: list[str] = []
    start = previous = None
    for vlan in [*vlans, None]:
        if vlan is not None and previous is not None and vlan == previous + 1:
            previous = vlan
            continue
        if start is not None:
            parts.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = vlan
    return ",".join(parts)


def show_switchport(lab: Lab, state: DeviceState) -> str:
    blocks = []
    names = {v.id: v.name for v in lab.topology.vlans}
    for port in ordered_ports(state):
        if port.mode is None:
            continue
        name = abbreviate(port.name)
        if port.mode is SwitchportMode.ROUTED:
            blocks.append(f"Name: {name}\nSwitchport: Disabled\n\n")
            continue
        trunk = port.mode is SwitchportMode.TRUNK
        operational = "trunk" if trunk else "static access"
        if port.channel is not None:
            operational = f"trunk (member of bundle Po{port.channel})"
        access = (
            f"{port.access_vlan} ({names.get(port.access_vlan or 0, 'default')})"
            if not trunk
            else "1 (default)"
        )
        allowed = vlan_list_text(port.allowed_vlans or ()) if trunk else "ALL"
        blocks.append(
            f"""Name: {name}
Switchport: Enabled
Administrative Mode: {"trunk" if trunk else "static access"}
Operational Mode: {operational}
Administrative Trunking Encapsulation: dot1q
Operational Trunking Encapsulation: {"dot1q" if trunk else "native"}
Negotiation of Trunking: {"On" if trunk else "Off"}
Access Mode VLAN: {access}
Trunking Native Mode VLAN: {port.native_vlan or 1} (default)
Administrative Native VLAN tagging: enabled
Voice VLAN: none
Administrative private-vlan host-association: none
Administrative private-vlan mapping: none
Operational private-vlan: none
Trunking VLANs Enabled: {allowed}
Pruning VLANs Enabled: 2-1001
Capture Mode Disabled
Capture VLANs Allowed: ALL

Protected: false
Unknown unicast blocked: disabled
Unknown multicast blocked: disabled
Appliance trust: none

"""
        )
    return "".join(blocks)


def show_etherchannel(state: DeviceState) -> str:
    rows = []
    for channel in etherchannels(state):
        members = "".join(f"{abbreviate(m)}({flag})      " for m, flag in channel.members)
        number = channel.port_channel[12:]
        rows.append(f"{number:<6} Po{number}(SU)         LACP        {members}")
    return (
        f"""Flags:  D - down        P - bundled in port-channel
        I - stand-alone s - suspended
        H - Hot-standby (LACP only)
        R - Layer3      S - Layer2
        U - in use      f - failed to allocate aggregator

        M - not in use, minimum links not met
        u - unsuitable for bundling
        w - waiting to be aggregated
        d - default port

        A - formed by Auto LAG


Number of channel-groups in use: {len(rows)}
Number of aggregators:           {len(rows)}

Group  Port-channel  Protocol    Ports
------+-------------+-----------+-----------------------------------------------
"""
        + "\n".join(rows)
        + "\n\n"
    )


def show_vlan_brief(lab: Lab, state: DeviceState) -> str:
    lines = [
        "",
        "VLAN Name                             Status    Ports",
        "---- -------------------------------- --------- -------------------------------",
    ]
    for vlan in vlans(lab, state):
        status = "act/unsup" if vlan.status.value == "unsupported" else "active"
        ports = [abbreviate(p) for p in vlan.ports]
        chunks = [ports[i : i + 4] for i in range(0, len(ports), 4)] or [[]]
        lines.append(f"{vlan.vlan_id:<4} {vlan.name or '':<32} {status:<9} {', '.join(chunks[0])}")
        lines.extend(f"{'':<48}{', '.join(chunk)}" for chunk in chunks[1:])
    return "\n".join(lines) + "\n"


def show_mac_table(state: DeviceState) -> str:
    lines = [
        "          Mac Address Table",
        "-------------------------------------------",
        "",
        "Vlan    Mac Address       Type        Ports",
        "----    -----------       --------    -----",
        " All    0100.0ccc.cccc    STATIC      CPU",
        " All    0180.c200.0000    STATIC      CPU",
    ]
    for entry in state.macs:
        lines.append(
            f"{entry.vlan_id:>4}    {dotted(entry.mac)}    DYNAMIC     "
            f"{abbreviate(entry.interface or '')}"
        )
    lines.append(f"Total Mac Addresses for this criterion: {len(state.macs) + 2}")
    return "\n".join(lines) + "\n"


def show_ip_arp(state: DeviceState) -> str:
    lines = ["Protocol  Address          Age (min)  Hardware Addr   Type   Interface"]
    for entry in state.arps:
        age = state.arp_ages.get(entry.ip, "5")
        lines.append(
            f"Internet  {entry.ip:<16} {age:>5}   {dotted(entry.mac)}  ARPA   {entry.interface}"
        )
    return "\n".join(lines) + "\n"


# --- routing --------------------------------------------------------------------------------

_ROUTE_CODES = {
    RouteProtocol.CONNECTED: "C",
    RouteProtocol.LOCAL: "L",
    RouteProtocol.STATIC: "S",
    RouteProtocol.OSPF: "O",
}
_CODES_HEADER = """Codes: L - local, C - connected, S - static, R - RIP, M - mobile, B - BGP
       D - EIGRP, EX - EIGRP external, O - OSPF, IA - OSPF inter area
       N1 - OSPF NSSA external type 1, N2 - OSPF NSSA external type 2
       E1 - OSPF external type 1, E2 - OSPF external type 2, m - OMP
       n - NAT, Ni - NAT inside, No - NAT outside, Nd - NAT DIA
       i - IS-IS, su - IS-IS summary, L1 - IS-IS level-1, L2 - IS-IS level-2
       ia - IS-IS inter area, * - candidate default, U - per-user static route
       H - NHRP, G - NHRP registered, g - NHRP registration summary
       o - ODR, P - periodic downloaded static route, l - LISP
       a - application route
       + - replicated route, % - next hop override, p - overrides from PfR
       & - replicated local route overrides by connected
"""


def _major(prefix: str) -> ipaddress.IPv4Network:
    network = ipaddress.IPv4Network(prefix)
    first = int(str(network.network_address).split(".")[0])
    length = 8 if first < 128 else 16 if first < 192 else 24
    return ipaddress.IPv4Network(f"{network.network_address}/{length}", strict=False)


def _route_line(route: pm.Route, code: str) -> str:
    if route.protocol in (RouteProtocol.CONNECTED, RouteProtocol.LOCAL):
        return f"{code:<9}{route.prefix} is directly connected, {route.interface}"
    via = f"via {route.next_hop}"
    tail = f", 2d03h, {route.interface}" if route.interface else ""
    return f"{code:<9}{route.prefix} [{route.admin_distance}/{route.metric}] {via}{tail}"


def show_ip_route(state: DeviceState) -> str:
    if not state.is_l3:
        return f"""Default gateway is {state.default_gateway or "not set"}

Host               Gateway           Last Use    Total Uses  Interface
ICMP redirect cache is empty
"""
    lines = [_CODES_HEADER]
    gateway = state.gateway_of_last_resort
    lines.append(
        f"Gateway of last resort is {gateway} to network 0.0.0.0\n"
        if gateway
        else "Gateway of last resort is not set\n"
    )
    previous: pm.Route | None = None
    current_major = None
    routes = state.routes
    for index, route in enumerate(routes):
        if (
            previous is not None
            and previous.prefix == route.prefix
            and route.protocol is RouteProtocol.OSPF
        ):
            indent = " " * (9 + len(route.prefix) + 1)
            tail = f", 2d03h, {route.interface}" if route.interface else ""
            lines.append(
                f"{indent}[{route.admin_distance}/{route.metric}] via {route.next_hop}{tail}"
            )
            previous = route
            continue
        if route.prefix == "0.0.0.0/0":
            code = "S*" if route.protocol is RouteProtocol.STATIC else "O*E2"
            via = f"via {route.next_hop}"
            tail = f", 2d03h, {route.interface}" if route.interface else ""
            lines.append(f"{code:<6}0.0.0.0/0 [{route.admin_distance}/{route.metric}] {via}{tail}")
        else:
            major = _major(route.prefix)
            if major != current_major:
                members = [
                    r
                    for r in routes[index:]
                    if r.prefix != "0.0.0.0/0" and _major(r.prefix) == major
                ]
                prefixes = {r.prefix for r in members}
                masks = {ipaddress.IPv4Network(p).prefixlen for p in prefixes}
                lines.append(
                    f"      {major} is variably subnetted, "
                    f"{len(prefixes)} subnets, {len(masks)} masks"
                )
                current_major = major
            lines.append(_route_line(route, _ROUTE_CODES[route.protocol]))
        previous = route
    return "\n".join(lines) + "\n"


_HSRP_TEXT = {
    HsrpState.ACTIVE: "Active",
    HsrpState.STANDBY: "Standby",
    HsrpState.LISTEN: "Listen",
    HsrpState.SPEAK: "Speak",
    HsrpState.LEARN: "Learn",
    HsrpState.INIT: "Init",
}


def show_standby_brief(state: DeviceState) -> str:
    if not state.hsrp:
        return ""
    lines = [
        "                     P indicates configured to preempt.",
        "                     |",
        "Interface   Grp  Pri P State   Active          Standby         Virtual IP",
    ]
    for group in state.hsrp:
        active = "local" if group.active_is_local else (group.active_router or "unknown")
        standby = "local" if group.standby_is_local else (group.standby_router or "unknown")
        lines.append(
            f"{abbreviate(group.interface):<11} {group.group:<4} {group.priority:<3} "
            f"{'P' if group.preempt else ' '} {_HSRP_TEXT[group.state]:<7} "
            f"{active:<15} {standby:<15} {group.virtual_ip}"
        )
    return "\n".join(lines) + "\n"


def show_ospf_neighbors(state: DeviceState) -> str:
    lines = ["", "Neighbor ID     Pri   State           Dead Time   Address         Interface"]
    for neighbor in state.ospf_neighbors:
        word = "FULL" if neighbor.state is OspfNeighborState.FULL else "2WAY"
        state_text = f"{word}/{neighbor.role}" if neighbor.role else f"{word}/  -"
        priority = 1 if neighbor.role else 0
        lines.append(
            f"{neighbor.router_id:<15} {priority:>3}   {state_text:<15} 00:00:35    "
            f"{neighbor.address:<15} {neighbor.interface}"
        )
    return "\n".join(lines) + "\n"


def show_ospf_interfaces(state: DeviceState) -> str:
    lines = ["Interface    PID   Area            IP Address/Mask    Cost  State Nbrs F/C"]
    for interface in state.ospf_interfaces:
        count = sum(1 for n in state.ospf_neighbors if n.interface == interface.interface)
        full = sum(
            1
            for n in state.ospf_neighbors
            if n.interface == interface.interface and n.state is OspfNeighborState.FULL
        )
        lines.append(
            f"{abbreviate(interface.interface):<12} {interface.process:<5} {interface.area:<15} "
            f"{interface.address or '':<18} {interface.cost:<5} {interface.state:<5} {full}/{count}"
        )
    return "\n".join(lines) + "\n"


_STP_ROLES = {
    StpPortRole.ROOT: "Root",
    StpPortRole.DESIGNATED: "Desg",
    StpPortRole.ALTERNATE: "Altn",
    StpPortRole.BACKUP: "Back",
    StpPortRole.DISABLED: "Disa",
}
_STP_STATES = {
    StpPortState.FORWARDING: "FWD",
    StpPortState.BLOCKING: "BLK",
    StpPortState.LEARNING: "LRN",
    StpPortState.LISTENING: "LIS",
    StpPortState.DISABLED: "DIS",
    StpPortState.BROKEN: "BKN",
}


def _stp_port_number(port: Port) -> int:
    """IOS numbers port-channels from 2081 (Po1) in the Prio.Nbr column."""
    if port.kind is InterfaceKind.PORT_CHANNEL:
        return 2080 + int(port.name.removeprefix("Port-channel"))
    return port.number


def show_spanning_tree(state: DeviceState) -> str:
    stp = state.stp
    if stp is None:
        return ""
    blocks = []
    for instance in stp.instances:
        priority, address = instance.root_bridge_id.split(" ")
        priority_base = state.device.stp_priority
        bridge_priority = priority_base + instance.vlan_id
        if instance.is_root:
            root_lines = f"""  Root ID    Priority    {priority}
             Address     {address}
             This bridge is the root
             Hello Time   2 sec  Max Age 20 sec  Forward Delay 15 sec
"""
        else:
            number = _stp_port_number(state.ports[instance.root_interface or ""])
            root_lines = f"""  Root ID    Priority    {priority}
             Address     {address}
             Cost        {instance.root_cost}
             Port        {number} ({instance.root_interface})
             Hello Time   2 sec  Max Age 20 sec  Forward Delay 15 sec
"""
        rows = []
        for port in stp.ports:
            if port.vlan_id != instance.vlan_id:
                continue
            local = state.ports[port.interface]
            kind = "P2p Edge" if local.edge else "P2p"
            rows.append(
                f"{abbreviate(port.interface):<19} {_STP_ROLES[port.role]} "
                f"{_STP_STATES[port.state]} {port.cost:<9} 128.{_stp_port_number(local):<5} {kind} "
            )
        blocks.append(
            f"""
VLAN{instance.vlan_id:04d}
  Spanning tree enabled protocol rstp
{root_lines}
  Bridge ID  Priority    {bridge_priority}  (priority {priority_base} sys-id-ext {instance.vlan_id})
             Address     {dotted(state.bridge_mac)}
             Hello Time   2 sec  Max Age 20 sec  Forward Delay 15 sec
             Aging Time  300 sec

Interface           Role Sts Cost      Prio.Nbr Type
------------------- ---- --- --------- -------- --------------------------------
"""
            + "\n".join(rows)
            + "\n\n"
        )
    return "".join(blocks)
