"""The fake lab generator: every rendered output parses, with our own parsers, into exactly
the state the topology file describes."""

import ipaddress
from functools import cache
from pathlib import Path

import pytest

from netops.core.ifname import normalize
from netops.db.enums import HsrpState, StpPortRole, SwitchportMode
from netops.parsing import models as pm
from netops.parsing.cisco_ios import PARSERS, parse
from netops_fakes import lab as fakelab
from netops_fakes.render import render
from netops_fakes.topology import Kind, Topology, load, synthetic

TOPOLOGY = Path(__file__).resolve().parents[2] / "lab" / "fakelab" / "topology.yaml"
ALLOWED = ipaddress.IPv4Network("10.255.0.0/24")


@cache
def fake_lab() -> fakelab.Lab:
    return fakelab.build(load(TOPOLOGY))


@cache
def parsed(name: str) -> dict[str, object]:
    """Parsed output of every command of one fake lab device."""
    lab = fake_lab()
    return {
        command: parse(command, text) for command, text in render(lab, lab.devices[name]).items()
    }


def short(name: str | None) -> str:
    return (name or "").split(".")[0]


CASES = [
    (state.name, command) for state in fake_lab().served() for command in sorted(state.expected)
]


@pytest.mark.parametrize(("device", "command"), CASES)
def test_rendered_output_parses_into_the_expected_models(device: str, command: str) -> None:
    lab = fake_lab()
    state = lab.devices[device]
    got = parse(command, render(lab, state)[command])
    expected = state.expected[command]
    assert got == (list(expected) if isinstance(expected, list) else expected)


def test_every_parser_is_exercised() -> None:
    switch = fake_lab().devices["core1"]
    assert set(render(fake_lab(), switch)) == set(PARSERS)


def test_router_and_l2_switches_only_serve_their_commands() -> None:
    lab = fake_lab()
    router = render(lab, lab.devices["rtr1"])
    assert "show vlan brief" not in router
    assert "show spanning-tree" not in router
    access = render(lab, lab.devices["access1"])
    assert "show standby brief" not in access
    assert access["show ip route"].startswith("Default gateway is 10.255.0.1")


def test_devices_parse_into_what_the_topology_describes() -> None:
    topology = fake_lab().topology
    for device in topology.devices:
        if device.external:
            continue
        facts = parsed(device.name)["show version"]
        assert isinstance(facts, pm.Facts)
        assert facts.hostname == device.name
        assert facts.serials == tuple(device.serials)
        assert facts.model == device.model
        assert facts.os_version == device.version
        inventory = parsed(device.name)["show inventory"]
        assert isinstance(inventory, list)
        assert [item.serial for item in inventory] == device.serials


def links_from_neighbors(topology: Topology, protocol: str) -> set[frozenset[tuple[str, str]]]:
    """Links as the parsed CDP (or LLDP) output of the served devices reports them."""
    links = set()
    for device in topology.devices:
        if device.external:
            continue
        neighbors = parsed(device.name)[f"show {protocol} neighbors detail"]
        assert isinstance(neighbors, list)
        for neighbor in neighbors:
            remote = (short(neighbor.remote_name), normalize(neighbor.remote_port or ""))
            links.add(frozenset({(device.name, neighbor.local_interface), remote}))
    return links


def test_cdp_from_both_sides_reproduces_every_link() -> None:
    lab = fake_lab()
    assert links_from_neighbors(lab.topology, "cdp") == lab.expected_links()


def test_lldp_reports_every_link_between_managed_ios_devices() -> None:
    lab = fake_lab()
    external = {d.name for d in lab.topology.devices if d.external}
    expected = {
        link for link in lab.expected_links() if not any(name in external for name, _ in link)
    }
    assert links_from_neighbors(lab.topology, "lldp") == expected


def test_neighbors_advertise_the_management_address_of_the_right_vlan() -> None:
    def advertised(device: str, remote: str) -> set[str | None]:
        neighbors = parsed(device)["show cdp neighbors detail"]
        assert isinstance(neighbors, list)
        return {n.remote_mgmt_ip for n in neighbors if short(n.remote_name) == remote}

    # The stack is reachable via two addresses: VLAN 99 towards the cores, VLAN 98 below.
    assert advertised("core1", "dist2") == {"10.255.0.12"}
    assert advertised("access3", "dist2") == {"10.255.0.70"}
    # The provider router's address is outside the allowed subnet.
    (isp,) = advertised("rtr1", "isp-ce1")
    assert isp is not None
    assert ipaddress.IPv4Address(isp) not in ALLOWED
    ap = parsed("access2")["show cdp neighbors detail"]
    assert isinstance(ap, list)
    assert any(n.remote_name == "ap1" and "Trans-Bridge" in n.remote_capabilities for n in ap)


def test_etherchannel_members_and_switchports() -> None:
    for core in ("core1", "core2"):
        (channel,) = parsed(core)["show etherchannel summary"]
        assert channel.port_channel == "Port-channel1"
        assert channel.members == (
            ("TenGigabitEthernet1/1/1", "P"),
            ("TenGigabitEthernet1/1/2", "P"),
        )
    ports = {p.interface: p for p in parsed("core1")["show interfaces switchport"]}
    assert ports["GigabitEthernet1/0/48"].mode is SwitchportMode.ROUTED
    assert ports["Port-channel1"].allowed_vlans == (10, 20, 30, 98, 99)


def test_vlans_hosts_mac_and_arp() -> None:
    topology = fake_lab().topology
    vlan_ids = {v.id for v in topology.vlans}
    for device in topology.devices:
        if device.external or device.kind is Kind.ROUTER:
            continue
        vlans = parsed(device.name)["show vlan brief"]
        assert isinstance(vlans, list)
        assert vlan_ids <= {v.vlan_id for v in vlans}
        by_vlan = {v.vlan_id: set(v.ports) for v in vlans}
        for host in device.hosts:
            assert host.port in by_vlan[host.vlan]
    # Every host is in the cores' ARP tables and learned on the access switch's host port.
    core_arp = {e.ip for e in parsed("core1")["show ip arp"]}
    for device in topology.devices:
        if device.external:
            continue
        macs = parsed(device.name).get("show mac address-table", [])
        assert isinstance(macs, list)
        local = {(e.vlan_id, e.interface) for e in macs}
        for host in device.hosts:
            assert str(host.ip) in core_arp
            assert (host.vlan, host.port) in local


def test_first_hop_redundancy_spanning_tree_and_ospf() -> None:
    topology = fake_lab().topology
    for core in ("core1", "core2"):
        groups = parsed(core)["show standby brief"]
        assert isinstance(groups, list)
        active = {g.group for g in groups if g.state is HsrpState.ACTIVE}
        expected = set(topology.device(core).hsrp_active)
        assert active == expected
    stp = parsed("core1")["show spanning-tree"]
    assert isinstance(stp, pm.SpanningTree)
    assert all(instance.is_root for instance in stp.instances)
    dist1 = parsed("dist1")["show spanning-tree"]
    assert isinstance(dist1, pm.SpanningTree)
    roles = {(p.vlan_id, p.interface): p.role for p in dist1.ports}
    assert roles[(10, "TenGigabitEthernet1/1/1")] is StpPortRole.ROOT  # towards core1
    assert roles[(10, "TenGigabitEthernet1/1/2")] is StpPortRole.ALTERNATE
    neighbors = parsed("rtr1")["show ip ospf neighbor"]
    assert isinstance(neighbors, list)
    assert {n.router_id for n in neighbors} == {"10.255.0.130", "10.255.0.131"}
    routes = parsed("rtr1")["show ip route"]
    assert isinstance(routes, list)
    default = next(r for r in routes if r.prefix == "0.0.0.0/0")
    assert default.next_hop == "198.51.100.1"


def test_fake_lab_uses_private_and_documentation_ranges_only() -> None:
    allowed = [ipaddress.IPv4Network(n) for n in ("10.0.0.0/8", "192.0.2.0/24", "198.51.100.0/24")]
    lab = fake_lab()
    for state in lab.devices.values():
        addresses = [state.device.mgmt_ip, *(h.ip for h in state.device.hosts)]
        addresses += [p.address.ip for p in state.ports.values() if p.address is not None]
        for address in addresses:
            assert any(address in network for network in allowed), (state.name, address)
        if not state.device.external:
            assert state.device.mgmt_ip in ALLOWED


@pytest.mark.parametrize("n", [6, 50, 200])
def test_synthetic_topologies_have_the_same_structure_and_round_trip(n: int) -> None:
    topology = synthetic(n)
    assert len(topology.devices) == n
    lab = fakelab.build(topology)
    kinds = [d.kind for d in topology.devices]
    assert kinds.count(Kind.ROUTER) == 1
    assert kinds.count(Kind.L3_SWITCH) == 2
    # Spot-check the round trip on one device of each kind (the full lab is checked above).
    for name in ("rtr1", "core1", "dist1", "access1"):
        state = lab.devices[name]
        for command, text in render(lab, state).items():
            expected = state.expected[command]
            got = parse(command, text)
            assert got == (list(expected) if isinstance(expected, list) else expected), command
    cdp_links = set()
    for state in lab.served():
        for neighbor in state.cdp:
            remote = (short(neighbor.remote_name), neighbor.remote_port or "")
            cdp_links.add(frozenset({(state.name, neighbor.local_interface), remote}))
    assert cdp_links == lab.expected_links()


def test_synthetic_rejects_sizes_outside_the_address_plan() -> None:
    with pytest.raises(ValueError, match="between 6 and 240"):
        synthetic(500)
