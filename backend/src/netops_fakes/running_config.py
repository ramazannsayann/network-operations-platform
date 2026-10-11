"""``show running-config`` of a fake device, consistent with its other outputs.

Rendered from the same derived state as every other command (netops_fakes.lab): VLANs,
trunks and their allowed VLANs, access ports, port-channels, routed links, SVIs with HSRP,
OSPF, descriptions and shut ports. Operational state (a port down because its peer is)
does not change the configuration; only what an operator configures does. Secrets come
from netops_fakes.fake_secrets. The header carries the volatile lines the normalizer
removes, with the time and user of the device's last applied change.
"""

import re
from datetime import UTC, datetime
from ipaddress import IPv4Interface

from netops.db.enums import InterfaceKind, SwitchportMode
from netops_fakes.fake_secrets import FAKE_SECRETS
from netops_fakes.lab import DeviceState, Lab, Port, vlan_list_text
from netops_fakes.topology import Kind

# When the lab's configurations were last saved, for devices nobody has changed since.
BASELINE = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
BASELINE_USER = "admin"
TACACS_SERVER = "192.0.2.49"
NTP_SERVER = "192.0.2.123"
OSPF_PROCESS = 1


def ios_time(when: datetime) -> str:
    """'09:00:00 UTC Mon Oct 5 2026' (as in the running-config header)."""
    when = when.astimezone(UTC)
    return f"{when:%H:%M:%S} UTC {when:%a %b} {when.day} {when.year}"


_TYPE_ORDER = (
    "FastEthernet",
    "GigabitEthernet",
    "TwoGigabitEthernet",
    "FiveGigabitEthernet",
    "TenGigabitEthernet",
    "TwentyFiveGigE",
    "FortyGigabitEthernet",
    "HundredGigE",
)


def _order(port: Port) -> tuple[int, int, tuple[int, ...]]:
    """IOS order: loopbacks, port-channels, physical ports by type and number, SVIs."""
    rank = {
        InterfaceKind.LOOPBACK: 0,
        InterfaceKind.PORT_CHANNEL: 1,
        InterfaceKind.PHYSICAL: 2,
        InterfaceKind.SVI: 3,
    }
    match = re.fullmatch(r"([A-Za-z-]+)([\d/.:]+)", port.name)
    kind, numbers = (match.group(1), match.group(2)) if match else (port.name, "")
    type_rank = _TYPE_ORDER.index(kind) if kind in _TYPE_ORDER else len(_TYPE_ORDER)
    return (
        rank.get(port.kind, 4),
        type_rank,
        tuple(int(n) for n in re.split(r"[/.:]", numbers) if n.isdigit()),
    )


def _address(address: IPv4Interface) -> str:
    return f" ip address {address.ip} {address.netmask}"


def _management_interface(state: DeviceState) -> str | None:
    """The interface that owns the management address (syslog source)."""
    for port in state.ports.values():
        if port.address is not None and port.address.ip == state.device.mgmt_ip:
            return port.name
    return None


def _hsrp_active(lab: Lab, vlan: int) -> str | None:
    cores = [d for d in lab.devices.values() if d.kind is Kind.L3_SWITCH]
    if len(cores) < 2:
        return None
    return next((c.name for c in cores if vlan in c.device.hsrp_active), cores[0].name)


def _external_link(lab: Lab, port: Port) -> bool:
    return port.peer is not None and lab.devices[port.peer[0]].device.external


def _ospf_adjacency(lab: Lab, state: DeviceState, port: Port) -> bool:
    if port.kind is InterfaceKind.SVI:
        vlan = lab.topology.vlan_of(state.device.mgmt_ip)
        return vlan is not None and port.name == f"Vlan{vlan.id}"
    return port.kind is InterfaceKind.PHYSICAL and not _external_link(lab, port)


def _ospf(state: DeviceState) -> bool:
    return state.is_l3 and state.device.loopback is not None


def _interface(lab: Lab, state: DeviceState, port: Port) -> list[str]:
    lines = [f"interface {port.name}"]
    if port.description:
        lines.append(f" description {port.description}")
    if port.mode is SwitchportMode.TRUNK:
        if port.native_vlan not in (None, 1):
            lines.append(f" switchport trunk native vlan {port.native_vlan}")
        lines.append(f" switchport trunk allowed vlan {vlan_list_text(port.allowed_vlans or ())}")
        lines.append(" switchport mode trunk")
    elif port.mode is SwitchportMode.ACCESS:
        lines.append(f" switchport access vlan {port.access_vlan}")
        lines.append(" switchport mode access")
    elif port.mode is SwitchportMode.ROUTED:
        lines.append(" no switchport")
    if port.address is not None:
        lines.append(_address(port.address))
        if _ospf(state) and port.kind is InterfaceKind.PHYSICAL and not _external_link(lab, port):
            lines.append(" ip ospf authentication message-digest")
            lines.append(f" ip ospf message-digest-key 1 md5 7 {FAKE_SECRETS['ospf_key']}")
    if port.kind is InterfaceKind.SVI and state.kind is Kind.L3_SWITCH:
        vlan = lab.topology.vlan(int(port.name[4:]))
        group = vlan.id
        lines.append(f" standby {group} ip {vlan.gateway}")
        if _hsrp_active(lab, vlan.id) == state.name:
            lines.append(f" standby {group} priority 110")
            lines.append(f" standby {group} preempt")
        lines.append(f" standby {group} authentication md5 key-string 7 {FAKE_SECRETS['hsrp_key']}")
    if not port.admin_up:
        lines.append(" shutdown")
    if port.edge and port.mode is SwitchportMode.ACCESS:
        lines.append(" spanning-tree portfast")
    if port.channel is not None:
        lines.append(f" channel-group {port.channel} mode active")
    if state.kind is Kind.ROUTER and port.kind is InterfaceKind.PHYSICAL:
        lines.append(" negotiation auto")
    return [*lines, "!"]


def _body(lab: Lab, state: DeviceState) -> list[str]:
    device = state.device
    major_minor = ".".join(device.version.split("(")[0].split(".")[:2])
    lines = [
        f"version {major_minor}",
        "service timestamps debug datetime msec",
        "service timestamps log datetime msec localtime show-timezone",
        "service password-encryption",
    ]
    if device.os == "ios":
        lines.append("service sequence-numbers")
    lines += [
        "!",
        f"hostname {device.name}",
        "!",
        "boot-start-marker",
        "boot-end-marker",
        "!",
        "logging buffered 64000 informational",
        "no logging console",
        f"enable secret 9 {FAKE_SECRETS['enable']}",
        "!",
        "aaa new-model",
        "!",
        "aaa group server tacacs+ LAB-TACACS",
        " server name LAB-TACACS-1",
        "!",
        "aaa authentication login default group LAB-TACACS local",
        "aaa authorization exec default group LAB-TACACS local if-authenticated",
        "aaa accounting commands 15 default start-stop group LAB-TACACS",
        "!",
        "aaa session-id common",
        "clock timezone UTC 0 0",
    ]
    if state.kind is Kind.L3_SWITCH:
        lines.append("ip routing")
    lines += ["!", f"ip domain name {lab.topology.domain}", "!", "login on-success log", "!"]
    if state.is_switch:
        lines += ["vtp mode transparent", "!", "spanning-tree mode rapid-pvst"]
        lines.append("spanning-tree extend system-id")
        if device.stp_priority != 32768:
            vlans = vlan_list_text(state.vlan_ids)
            lines.append(f"spanning-tree vlan {vlans} priority {device.stp_priority}")
        lines.append("!")
    lines += [
        f"username admin privilege 15 secret 9 {FAKE_SECRETS['user_admin']}",
        f"username netops-ro privilege 15 secret 9 {FAKE_SECRETS['user_readonly']}",
        "!",
    ]
    if state.is_switch:
        for vlan in lab.topology.vlans:
            lines += [f"vlan {vlan.id}", f" name {vlan.name}", "!"]
    for port in sorted(state.ports.values(), key=_order):
        lines += _interface(lab, state, port)
    if _ospf(state):
        lines += [f"router ospf {OSPF_PROCESS}", f" router-id {device.loopback}"]
        lines.append(" passive-interface default")
        addressed = [p for p in sorted(state.ports.values(), key=_order) if p.address]
        lines += [
            f" no passive-interface {p.name}" for p in addressed if _ospf_adjacency(lab, state, p)
        ]
        for port in addressed:
            if not _external_link(lab, port) and port.address is not None:
                lines.append(f" network {port.address.ip} 0.0.0.0 area 0")
        lines.append("!")
    if state.kind is Kind.ROUTER:
        for port in state.ports.values():
            if _external_link(lab, port) and port.address is not None and port.peer:
                peer = lab.devices[port.peer[0]].ports[port.peer[1]]
                if peer.address is not None:
                    lines.append(f"ip route 0.0.0.0 0.0.0.0 {peer.address.ip}")
    elif not state.is_l3 and state.default_gateway:
        lines.append(f"ip default-gateway {state.default_gateway}")
    lines += ["ip ssh version 2", "ip scp server enable", "!", "logging origin-id hostname"]
    source = _management_interface(state)
    if source is not None:
        lines.append(f"logging source-interface {source}")
    if lab.topology.syslog_host is not None:
        lines.append(f"logging host {lab.topology.syslog_host}")
    lines += [
        "!",
        f"snmp-server community {FAKE_SECRETS['snmp_community']} RO",
        "snmp-server location Fake lab, rack 1",
        "snmp-server contact netops-lab@example.net",
        "!",
        "tacacs server LAB-TACACS-1",
        f" address ipv4 {TACACS_SERVER}",
        f" key 7 {FAKE_SECRETS['tacacs_key']}",
        "!",
        "banner motd ^C",
        f"{device.name}: fake lab device. Authorized use only.",
        "^C",
        "!",
        "line con 0",
        " exec-timeout 15 0",
        " stopbits 1",
        "line vty 0 4",
        " exec-timeout 15 0",
        f" password 7 {FAKE_SECRETS['line_vty']}",
        " transport input ssh",
        "line vty 5 15",
        " transport input ssh",
        "!",
        f"ntp authentication-key 1 md5 {FAKE_SECRETS['ntp_key']} 7",
        "ntp authenticate",
        "ntp trusted-key 1",
    ]
    if device.os == "ios":
        lines.append("ntp clock-period 36028747")  # drifts between backups: volatile
    lines += [
        f"ntp server {NTP_SERVER} key 1",
        "!",
        "archive",
        " log config",
        "  logging enable",
        "  logging size 200",
        "  notify syslog contenttype plaintext",
        "  hidekeys",
        "!",
        "end",
    ]
    return lines


def show_running_config(lab: Lab, state: DeviceState) -> str:
    body = "\n".join(_body(lab, state)) + "\n"
    change = lab.topology.last_change(state.name)
    changed_at, changed_by = (change.at, change.user) if change else (BASELINE, BASELINE_USER)
    return (
        "Building configuration...\n\n"
        f"Current configuration : {len(body.encode())} bytes\n"
        "!\n"
        f"! Last configuration change at {ios_time(changed_at)} by {changed_by}\n"
        f"! NVRAM config last updated at {ios_time(BASELINE)} by {BASELINE_USER}\n"
        "!\n" + body
    )
