"""Parsers against the fixtures in lab/fixtures (ntc-templates outputs and the dist-sw1 lab)."""

from pathlib import Path

import pytest

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
from netops.parsing import PARSERS, CommandError, ParseError, parse
from netops.parsing import normalize as canon
from netops.parsing.models import (
    EtherChannel,
    Facts,
    HsrpGroup,
    InterfaceStatus,
    MacEntry,
    Neighbor,
    Route,
    SpanningTree,
    Switchport,
    Vlan,
)

FIXTURES = Path(__file__).resolve().parents[2] / "lab" / "fixtures"
IOS = FIXTURES / "cisco_ios"
LAB = FIXTURES / "devices" / "dist-sw1"
# Fixture directory -> the command whose output it holds.
DIRECTORY_COMMANDS = {command.replace(" ", "_"): command for command in PARSERS} | {
    "show_vlan": "show vlan brief"  # ntc's "show vlan" output; same template
}


def ios(directory: str, name: str) -> str:
    return (IOS / directory / name).read_text()


def lab(command: str) -> str:
    return (LAB / f"{command.replace(' ', '_')}.raw").read_text()


ALL_FIXTURES = sorted(
    [(DIRECTORY_COMMANDS[path.parent.name], path) for path in IOS.glob("*/*.raw")]
    + [(command, LAB / f"{command.replace(' ', '_')}.raw") for command in PARSERS]
)


def test_every_command_has_fixtures() -> None:
    commands = {command for command, _ in ALL_FIXTURES}
    assert commands == set(PARSERS)
    assert len(ALL_FIXTURES) >= 70


@pytest.mark.parametrize(
    ("command", "path"),
    ALL_FIXTURES,
    ids=[f"{path.parent.name}/{path.name}" for _, path in ALL_FIXTURES],
)
def test_every_fixture_parses(command: str, path: Path) -> None:
    result = parse(command, path.read_text())
    assert isinstance(result, list | Facts | SpanningTree)


# --- show version / show inventory ------------------------------------------------------------


def test_version_of_a_four_member_ios_xe_stack() -> None:
    facts = parse("show version", ios("show_version", "cisco_ios_show_version1.raw"))
    assert isinstance(facts, Facts)
    assert facts.os_family is OsFamily.IOSXE
    assert facts.model == "WS-C3850-48U"
    assert facts.serials == ("FOC11111111", "FCW22222222", "FCW33333333", "FCW44444444")


def test_version_of_classic_ios() -> None:
    facts = parse("show version", ios("show_version", "cisco_ios_show_version.raw"))
    assert isinstance(facts, Facts)
    assert (facts.hostname, facts.os_family, facts.os_version) == (
        "router1",
        OsFamily.IOS,
        "12.2(54)SG1",
    )
    assert facts.serials == ("CAT1451S15C",)


def test_version_deduplicates_repeated_serials() -> None:
    facts = parse("show version", ios("show_version", "cisco_ios_show_version5.raw"))
    assert isinstance(facts, Facts)
    assert facts.serials == ("CAT23XXXXXX",)


def test_lab_version_and_inventory_stack_members() -> None:
    facts = parse("show version", lab("show version"))
    assert facts == Facts(
        hostname="dist-sw1",
        os_family=OsFamily.IOSXE,
        os_version="17.9.4a",
        model="C9300-48P",
        serials=("FOC0000X0A1", "FOC0000X0B2"),
        uptime="6 weeks, 2 days, 3 hours, 12 minutes",
    )
    items = parse("show inventory", lab("show inventory"))
    assert isinstance(items, list)
    members = {item.stack_member: item.serial for item in items if item.stack_member}
    assert members == {1: "FOC0000X0A1", 2: "FOC0000X0B2"}


def test_empty_version_output_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        parse("show version", "")


# --- neighbours -------------------------------------------------------------------------------


def test_cdp_neighbours_use_canonical_interface_names() -> None:
    neighbors = parse("show cdp neighbors detail", lab("show cdp neighbors detail"))
    assert isinstance(neighbors, list)
    assert neighbors[2] == Neighbor(
        protocol=NeighborProtocol.CDP,
        local_interface="GigabitEthernet1/0/3",
        remote_name="sw-b2-03.lab.example.net",
        remote_mgmt_ip="10.0.0.23",
        remote_port="GigabitEthernet1/0/49",
        remote_platform="cisco WS-C2960X-48FPD-L",
        remote_capabilities=("Switch", "IGMP"),
    )
    assert [n.local_interface for n in neighbors[:2]] == [
        "TenGigabitEthernet1/1/1",
        "TenGigabitEthernet2/1/1",
    ]


def test_lldp_neighbour_short_names_and_capabilities() -> None:
    (neighbor,) = parse("show lldp neighbors detail", lab("show lldp neighbors detail"))  # type: ignore[misc]
    assert neighbor.local_interface == "GigabitEthernet1/0/5"
    assert neighbor.remote_port == "Gi0"
    assert neighbor.remote_mgmt_ip == "10.0.30.21"
    assert neighbor.remote_capabilities == ("bridge",)


@pytest.mark.parametrize(
    "name",
    ["cisco_ios_show_lldp_neighbors_detail2.raw", "cisco_ios_show_lldp_neighbors_detail5.raw"],
)
def test_lldp_without_local_interface_is_skipped(name: str) -> None:
    assert parse("show lldp neighbors detail", ios("show_lldp_neighbors_detail", name)) == []


@pytest.mark.parametrize(
    ("command", "directory"),
    [
        ("show cdp neighbors detail", "show_cdp_neighbors_detail"),
        ("show lldp neighbors detail", "show_lldp_neighbors_detail"),
    ],
)
def test_disabled_protocol_means_no_neighbours(command: str, directory: str) -> None:
    assert parse(command, ios(directory, "netops_not_enabled.raw")) == []


# --- interfaces -------------------------------------------------------------------------------


def _by_name(items: list[InterfaceStatus]) -> dict[str, InterfaceStatus]:
    return {item.name: item for item in items}


def test_lab_interfaces_status_and_counters() -> None:
    interfaces = _by_name(parse("show interfaces", lab("show interfaces")))  # type: ignore[arg-type]
    assert interfaces["GigabitEthernet1/0/2"].admin_up is False
    assert interfaces["GigabitEthernet1/0/4"].err_disabled is True
    assert interfaces["GigabitEthernet1/0/4"].oper_up is False
    duplex_mismatch = interfaces["GigabitEthernet1/0/5"]
    assert (duplex_mismatch.duplex, duplex_mismatch.speed_mbps) == (Duplex.HALF, 100)
    assert duplex_mismatch.late_collisions == 27
    assert interfaces["GigabitEthernet1/0/3"].crc_errors == 12
    assert interfaces["Vlan20"].address == "10.0.20.2/24"
    assert interfaces["Vlan20"].mac == "00:a7:42:d1:00:14"
    assert interfaces["Port-channel1"].kind is InterfaceKind.PORT_CHANNEL
    assert interfaces["Loopback0"].kind is InterfaceKind.LOOPBACK
    assert interfaces["TenGigabitEthernet1/1/1"].speed_mbps == 10_000


def test_twenty_five_gig_names_are_normalized() -> None:
    interfaces = parse("show interfaces", ios("show_interfaces", "cisco_ios_show_interfaces6.raw"))
    assert isinstance(interfaces, list)
    assert all(i.name.startswith("TwentyFiveGigE") for i in interfaces)


def test_scrubbed_address_is_parsed_with_prefix() -> None:
    interfaces = parse(
        "show interfaces", ios("show_interfaces", "cisco_ios_show_interfaces_01.raw")
    )
    assert "198.51.100.37/30" in {i.address for i in interfaces}  # type: ignore[union-attr]


def test_switchport_modes_and_vlan_lists() -> None:
    ports = {
        p.interface: p
        for p in parse("show interfaces switchport", lab("show interfaces switchport"))  # type: ignore[union-attr]
    }
    assert ports["GigabitEthernet1/0/1"] == Switchport(
        "GigabitEthernet1/0/1", SwitchportMode.ACCESS, 20, None, None
    )
    # Down ports fall back to their static administrative mode.
    assert ports["GigabitEthernet1/0/2"].mode is SwitchportMode.ACCESS
    member = ports["TenGigabitEthernet1/1/1"]  # "trunk (member of bundle Po1)"
    assert (member.mode, member.native_vlan, member.allowed_vlans) == (
        SwitchportMode.TRUNK,
        99,
        (20, 30, 99),
    )


def test_trunk_vlan_ranges_are_expanded() -> None:
    ports = parse(
        "show interfaces switchport",
        ios("show_interfaces_switchport", "cisco_ios_show_interfaces_switchport2.raw"),
    )
    assert isinstance(ports, list)
    allowed = ports[0].allowed_vlans
    assert allowed is not None
    assert {31, 32, 33, 34, 35, 36, 40, 41, 42, 940} <= set(allowed)
    assert 37 not in allowed


def test_trunk_allowing_all_vlans() -> None:
    ports = parse(
        "show interfaces switchport",
        ios("show_interfaces_switchport", "cisco_ios_show_interfaces_switchport.raw"),
    )
    trunks = [p for p in ports if p.mode is SwitchportMode.TRUNK]  # type: ignore[union-attr]
    assert trunks
    assert all(p.allowed_vlans == tuple(range(1, 4095)) for p in trunks)


def test_etherchannel_members() -> None:
    assert parse("show etherchannel summary", lab("show etherchannel summary")) == [
        EtherChannel(
            "Port-channel1",
            "LACP",
            (("TenGigabitEthernet1/1/1", "P"), ("TenGigabitEthernet2/1/1", "P")),
        )
    ]
    channels = parse(
        "show etherchannel summary",
        ios("show_etherchannel_summary", "show_etherchannel_summary.raw"),
    )
    assert isinstance(channels, list)
    assert channels[0].port_channel == "Port-channel1"
    assert [m for m, _ in channels[0].members][:2] == [
        "TenGigabitEthernet6/4",
        "TenGigabitEthernet3/5",
    ]


def test_ip_interface_brief() -> None:
    rows = {
        r.interface: r for r in parse("show ip interface brief", lab("show ip interface brief"))
    }  # type: ignore[union-attr]
    assert rows["Vlan99"].address == "10.0.0.11"
    assert rows["Vlan1"].admin_up is False
    assert rows["GigabitEthernet1/0/4"].oper_up is False


# --- VLANs, MAC and ARP ---------------------------------------------------------------------


def test_vlan_statuses() -> None:
    vlans = {v.vlan_id: v for v in parse("show vlan brief", lab("show vlan brief"))}  # type: ignore[union-attr]
    assert vlans[20] == Vlan(
        20, "STAFF", VlanStatus.ACTIVE, ("GigabitEthernet1/0/1", "GigabitEthernet1/0/2")
    )
    assert vlans[666].status is VlanStatus.SHUTDOWN
    assert vlans[1003].status is VlanStatus.UNSUPPORTED
    assert len(vlans[1].ports) == 7  # ports continue on the next line


def test_mac_table_skips_cpu_entries() -> None:
    entries = parse("show mac address-table", lab("show mac address-table"))
    assert isinstance(entries, list)
    assert len(entries) == 8  # 12 lines minus 4 "All" CPU entries
    assert entries[0] == MacEntry(
        20, "3c:52:82:6e:41:9a", "GigabitEthernet1/0/1", MacEntryType.DYNAMIC
    )
    assert {e.interface for e in entries} >= {"Port-channel1"}


def test_mac_table_repeated_per_linecard_is_deduplicated() -> None:
    entries = parse(
        "show mac address-table",
        ios("show_mac_address-table", "cisco_ios_show_mac-address-table5.raw"),
    )
    assert entries == [MacEntry(420, "00:9e:1e:ad:ea:dd", "Port-channel140", MacEntryType.DYNAMIC)]


def test_empty_tables() -> None:
    assert parse("show mac address-table", ios("show_mac_address-table", "netops_empty.raw")) == []
    assert parse("show standby brief", ios("show_standby_brief", "netops_empty.raw")) == []
    assert parse("show ip ospf neighbor", ios("show_ip_ospf_neighbor", "netops_empty.raw")) == []


def test_arp_skips_incomplete_entries() -> None:
    entries = parse("show ip arp", lab("show ip arp"))
    assert isinstance(entries, list)
    assert len(entries) == 11
    assert ("10.0.20.57", "3c:52:82:6e:41:9a", "Vlan20") in {
        (e.ip, e.mac, e.interface) for e in entries
    }
    assert "10.0.30.99" not in {e.ip for e in entries}


# --- routing --------------------------------------------------------------------------------


def test_routes_with_ecmp_static_and_default() -> None:
    routes = parse("show ip route", lab("show ip route"))
    assert isinstance(routes, list)
    assert routes[0] == Route("0.0.0.0/0", RouteProtocol.OSPF, "10.0.0.1", "Vlan99", 110, 1, None)
    ecmp = [r for r in routes if r.prefix == "10.0.40.0/24"]
    assert {r.next_hop for r in ecmp} == {"10.0.0.1", "10.0.0.12"}
    static = next(r for r in routes if r.protocol is RouteProtocol.STATIC)
    assert (static.prefix, static.next_hop, static.interface) == ("10.9.0.0/16", "10.0.0.254", None)
    local = next(r for r in routes if r.prefix == "10.0.20.2/32")
    assert local.protocol is RouteProtocol.LOCAL


def test_routes_in_a_vrf() -> None:
    routes = parse("show ip route", ios("show_ip_route", "cisco_ios_show_ip_route_vrf.raw"))
    assert {r.vrf for r in routes} == {"TRI"}  # type: ignore[union-attr]
    assert "198.51.100.1/32" in {r.prefix for r in routes}  # type: ignore[union-attr]


def test_spanning_tree_root_and_ports() -> None:
    tree = parse("show spanning-tree", lab("show spanning-tree"))
    assert isinstance(tree, SpanningTree)
    vlan20 = tree.instances[0]
    assert (vlan20.vlan_id, vlan20.root_bridge_id, vlan20.root_cost) == (
        20,
        "24596 00a7.42c1.8000",
        1000,
    )
    assert (vlan20.root_interface, vlan20.is_root) == ("Port-channel1", False)
    roots = [p for p in tree.ports if p.role is StpPortRole.ROOT]
    assert {p.interface for p in roots} == {"Port-channel1"}
    assert all(p.state is StpPortState.FORWARDING for p in tree.ports)


def test_spanning_tree_root_bridge_detected() -> None:
    tree = parse(
        "show spanning-tree", ios("show_spanning-tree", "cisco_ios_show_spanning_tree.raw")
    )
    assert isinstance(tree, SpanningTree)
    assert tree.instances
    assert all(i.root_cost == 0 and i.root_interface is None for i in tree.instances if i.is_root)


def test_hsrp_local_active_and_standby() -> None:
    groups = parse("show standby brief", lab("show standby brief"))
    assert groups == [
        HsrpGroup(
            "Vlan20", 20, 110, True, HsrpState.ACTIVE, "10.0.20.1", None, True, "10.0.20.3", False
        ),
        HsrpGroup(
            "Vlan30", 30, 100, False, HsrpState.STANDBY, "10.0.30.1", "10.0.30.3", False, None, True
        ),
    ]


def test_ospf_neighbour_states_and_roles() -> None:
    neighbors = parse("show ip ospf neighbor", lab("show ip ospf neighbor"))
    assert isinstance(neighbors, list)
    assert [(n.router_id, n.state, n.role) for n in neighbors] == [
        ("10.255.0.1", OspfNeighborState.FULL, "DR"),
        ("10.255.0.12", OspfNeighborState.TWO_WAY, "DROTHER"),
    ]


def test_ospf_interface_areas() -> None:
    interfaces = parse("show ip ospf interface brief", lab("show ip ospf interface brief"))
    assert {(i.interface, i.area) for i in interfaces} >= {("Vlan99", 0), ("Loopback0", 0)}  # type: ignore[union-attr]


# --- CLI errors and value normalization ---------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "                    ^\n% Invalid input detected at '^' marker.\n",
        "% Incomplete command.\n",
        '% Ambiguous command:  "show i"\n',
    ],
)
def test_cli_errors_are_command_errors(answer: str) -> None:
    with pytest.raises(CommandError):
        parse("show standby brief", answer)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1-3,10", (1, 2, 3, 10)),
        (["1", "5-6", "4094"], (1, 5, 6, 4094)),
        ("NONE", ()),
        ("none", ()),
        ("", None),
        (None, None),
    ],
)
def test_vlan_list_expansion(raw: str | list[str] | None, expected: tuple[int, ...] | None) -> None:
    assert canon.vlan_list(raw) == expected


def test_vlan_list_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="VLAN list"):
        canon.vlan_list("1-3,abc")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0011.2233.4455", "00:11:22:33:44:55"),
        ("00-11-22-33-44-55", "00:11:22:33:44:55"),
        ("00:11:22:AA:BB:CC", "00:11:22:aa:bb:cc"),
        ("Incomplete", None),
        ("", None),
    ],
)
def test_mac_canonical_form(raw: str, expected: str | None) -> None:
    assert canon.mac(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1000Mb/s", 1000),
        ("10Gb/s", 10_000),
        ("a-100", 100),
        ("100Mbps", 100),
        ("Auto-speed", None),
    ],
)
def test_speed(raw: str, expected: int | None) -> None:
    assert canon.speed_mbps(raw) == expected


def test_ip_canonical_form() -> None:
    assert canon.ip("2001:DB8:0:0::1") == "2001:db8::1"
    assert canon.ip("unassigned") is None
    assert canon.ip_with_prefix("10.0.20.2", "24") == "10.0.20.2/24"
    assert canon.network("10.0.20.7", "24") == "10.0.20.0/24"
