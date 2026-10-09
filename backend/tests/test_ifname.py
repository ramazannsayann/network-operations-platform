"""netops.core.ifname.normalize with interface names as Cisco devices print them."""

import pytest

from netops.core.ifname import normalize


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # GigabitEthernet: show ip int brief, CDP, LLDP, show interfaces, descriptions
        ("Gi1/0/1", "GigabitEthernet1/0/1"),
        ("Gig 1/0/1", "GigabitEthernet1/0/1"),
        ("Gig1/0/1", "GigabitEthernet1/0/1"),
        ("Gi 1/0/1", "GigabitEthernet1/0/1"),
        ("GigabitEthernet1/0/1", "GigabitEthernet1/0/1"),
        ("GigabitEthernet 1/0/1", "GigabitEthernet1/0/1"),
        ("gigabitethernet1/0/1", "GigabitEthernet1/0/1"),
        ("GIGABITETHERNET1/0/1", "GigabitEthernet1/0/1"),
        ("gi0/1", "GigabitEthernet0/1"),
        ("Gigabit0/1", "GigabitEthernet0/1"),
        ("GigabitEth0/1", "GigabitEthernet0/1"),
        ("GigE0/0/0", "GigabitEthernet0/0/0"),
        ("Gi0/0/0", "GigabitEthernet0/0/0"),
        # FastEthernet (2960, older routers)
        ("Fa0/1", "FastEthernet0/1"),
        ("Fas 0/24", "FastEthernet0/24"),
        ("Fast0/1", "FastEthernet0/1"),
        ("FastEthernet0/1", "FastEthernet0/1"),
        # Ethernet (IOL images in CML, NX-OS style)
        ("Et0/0", "Ethernet0/0"),
        ("Eth1/1", "Ethernet1/1"),
        ("Ethernet0/3", "Ethernet0/3"),
        # Multi-gig and high-speed (Catalyst 9000)
        ("Tw1/0/1", "TwoGigabitEthernet1/0/1"),
        ("TwoGigabitEthernet1/0/1", "TwoGigabitEthernet1/0/1"),
        ("Fi1/0/1", "FiveGigabitEthernet1/0/1"),
        ("Te1/1/1", "TenGigabitEthernet1/1/1"),
        ("Ten 1/1/1", "TenGigabitEthernet1/1/1"),
        ("TenGig1/1/1", "TenGigabitEthernet1/1/1"),
        ("TenGigE0/0/0/0", "TenGigabitEthernet0/0/0/0"),
        ("TenGigabitEthernet1/1/1", "TenGigabitEthernet1/1/1"),
        ("Twe1/0/1", "TwentyFiveGigE1/0/1"),
        ("TwentyFiveGigE1/0/1", "TwentyFiveGigE1/0/1"),
        ("TwentyFiveGigabitEthernet1/0/1", "TwentyFiveGigE1/0/1"),
        ("Fo1/1/1", "FortyGigabitEthernet1/1/1"),
        ("FortyGigE1/1/1", "FortyGigabitEthernet1/1/1"),
        ("Hu1/0/49", "HundredGigE1/0/49"),
        ("HundredGigE1/0/49", "HundredGigE1/0/49"),
        ("HundredGigabitEthernet1/0/49", "HundredGigE1/0/49"),
        ("Ap1/0/1", "AppGigabitEthernet1/0/1"),
        # Logical interfaces
        ("Po1", "Port-channel1"),
        ("Po10", "Port-channel10"),
        ("Port-channel10", "Port-channel10"),
        ("Port-Channel10", "Port-channel10"),
        ("port-channel10", "Port-channel10"),
        ("PortChannel10", "Port-channel10"),
        ("Vl20", "Vlan20"),
        ("Vlan20", "Vlan20"),
        ("VLAN20", "Vlan20"),
        ("vlan 20", "Vlan20"),
        ("Lo0", "Loopback0"),
        ("Loopback0", "Loopback0"),
        ("Tu100", "Tunnel100"),
        ("Tunnel100", "Tunnel100"),
        ("Nu0", "Null0"),
        ("BD10", "BDI10"),
        ("Di1", "Dialer1"),
        ("Mu1", "Multilink1"),
        ("Vi1", "Virtual-Access1"),
        ("Vt1", "Virtual-Template1"),
        # WAN
        ("Se0/0/0", "Serial0/0/0"),
        ("Se0/0/0:1", "Serial0/0/0:1"),
        ("Ce0/1/0", "Cellular0/1/0"),
        # Subinterfaces keep their suffix
        ("Gi0/0.100", "GigabitEthernet0/0.100"),
        ("Po1.200", "Port-channel1.200"),
        ("Te0/1/0.10", "TenGigabitEthernet0/1/0.10"),
        # Surrounding whitespace (fixed-width CLI columns)
        ("  Gi1/0/1  ", "GigabitEthernet1/0/1"),
        ("\tFa0/1\n", "FastEthernet0/1"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mgmt0", "mgmt0"),  # NX-OS management port: unknown type, left as is
        ("Wlan-GigabitEthernet0", "Wlan-GigabitEthernet0"),
        ("Embedded-Service-Engine0/0", "Embedded-Service-Engine0/0"),
        ("T1/0/1", "T1/0/1"),  # ambiguous: Tunnel, TenGig, TwoGig, TwentyFive
        ("G1/0/1", "G1/0/1"),  # single letters are not trusted
        ("V1", "V1"),
        ("Vlan", "Vlan"),  # no number
        ("aabb.cc00.0100", "aabb.cc00.0100"),  # LLDP port ID that is a MAC address
        ("0011.2233.4455", "0011.2233.4455"),
        ("00:11:22:33:44:55", "00:11:22:33:44:55"),
        ("Gi1/0/1 uplink", "Gi1/0/1 uplink"),  # not a bare interface name
    ],
)
def test_unrecognised_names_are_kept(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["Gi1/0/1", "Twe1/0/1", "Po10.100", "Vi1", "mgmt0", "T1/0/1", "Port-Channel5", "vlan 20"],
)
def test_normalize_is_idempotent(raw: str) -> None:
    once = normalize(raw)
    assert normalize(once) == once


def test_spellings_of_one_port_converge() -> None:
    spellings = ["Gi1/0/1", "Gig 1/0/1", "GigabitEthernet1/0/1", "gi1/0/1", "GigE1/0/1"]
    assert {normalize(s) for s in spellings} == {"GigabitEthernet1/0/1"}


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_empty_name_is_rejected(raw: str) -> None:
    with pytest.raises(ValueError, match="empty"):
        normalize(raw)
