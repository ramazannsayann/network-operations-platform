"""The lab topology file: devices, links, VLANs and hosts (lab/fakelab/topology.yaml).

The same format describes the fake lab (rendered by netops_fakes.lab) and, with only
``devices`` and ``links`` filled in, a real lab for tools/eval/discovery_accuracy.py.
"""

import ipaddress
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from netops.core.ifname import normalize


class Kind(StrEnum):
    L3_SWITCH = "l3_switch"
    SWITCH = "switch"
    ROUTER = "router"
    AP = "ap"


class Credentials(StrEnum):
    """Which password the fake device accepts."""

    LAB = "lab"  # the lab password (FAKELAB_PASSWORD / the test fixture's)
    WRONG = "wrong"  # a random one nobody knows: discovery must report auth_failed


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Vlan(_Model):
    id: Annotated[int, Field(ge=2, le=1001)]
    name: str
    subnet: ipaddress.IPv4Network
    # Management VLANs carry the switches' management addresses.
    management: bool = False

    @property
    def gateway(self) -> ipaddress.IPv4Address:
        """HSRP virtual IP: the first host address."""
        return next(self.subnet.hosts())


class Host(_Model):
    port: str
    vlan: int
    ip: ipaddress.IPv4Address
    mac: str | None = None

    @field_validator("port")
    @classmethod
    def _port(cls, value: str) -> str:
        return normalize(value)


class ExtraSvi(_Model):
    """A second management SVI (the device is then reachable via two addresses)."""

    vlan: int
    ip: ipaddress.IPv4Address


class Device(_Model):
    name: str
    kind: Kind
    model: str
    os: Annotated[str, Field(pattern=r"^(ios|iosxe)$")] = "iosxe"
    version: str = "17.9.4a"
    serials: list[str] = Field(min_length=1)
    mgmt_ip: ipaddress.IPv4Address
    # Expected role, for evaluating the role heuristic.
    role: Annotated[str, Field(pattern=r"^(core|distribution|access|edge|unknown)$")] = "unknown"
    # Not served by a fake SSH server (an AP, a provider router outside the lab).
    external: bool = False
    credentials: Credentials = Credentials.LAB
    loopback: ipaddress.IPv4Address | None = None
    stp_priority: int = 32768
    hsrp_active: list[int] = Field(default_factory=list)
    extra_svis: list[ExtraSvi] = Field(default_factory=list)
    hosts: list[Host] = Field(default_factory=list)


class Endpoint(_Model):
    device: str
    port: str


class Link(_Model):
    """A cable. ``a``/``b`` as "device port"; ``subnet`` makes it a routed /30."""

    a: Endpoint
    b: Endpoint
    channel: int | None = None
    subnet: ipaddress.IPv4Network | None = None

    @model_validator(mode="before")
    @classmethod
    def _parse_endpoints(cls, data: object) -> object:
        if isinstance(data, dict):
            for side in ("a", "b"):
                value = data.get(side)
                if isinstance(value, str):
                    device, _, port = value.partition(" ")
                    data[side] = {"device": device, "port": normalize(port)}
        return data


class Topology(_Model):
    name: str
    domain: str = "lab.example.net"
    management_subnet: ipaddress.IPv4Network
    vlans: list[Vlan] = Field(default_factory=list)
    devices: list[Device]
    links: list[Link] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        names = [d.name for d in self.devices]
        if len(set(names)) != len(names):
            raise ValueError("device names must be unique")
        known = set(names)
        ports: set[tuple[str, str]] = set()
        for link in self.links:
            for end in (link.a, link.b):
                if end.device not in known:
                    raise ValueError(f"link endpoint {end.device!r} is not a device")
                if (end.device, end.port) in ports:
                    raise ValueError(f"port {end.device} {end.port} is used twice")
                ports.add((end.device, end.port))
        return self

    def device(self, name: str) -> Device:
        return next(d for d in self.devices if d.name == name)

    def vlan(self, vlan_id: int) -> Vlan:
        return next(v for v in self.vlans if v.id == vlan_id)

    def vlan_of(self, address: ipaddress.IPv4Address) -> Vlan | None:
        return next((v for v in self.vlans if address in v.subnet), None)


def load(path: Path) -> Topology:
    return Topology.model_validate(yaml.safe_load(path.read_text()))


def synthetic(n: int, *, name: str | None = None) -> Topology:
    """A campus of ``n`` managed devices with the fake lab's structure, for scale tests.

    1 router, 2 cores (EtherChannel between them), distribution switches dual-homed to the
    cores and access switches single-homed to a distribution switch, two hosts each.
    """
    if not 6 <= n <= 240:
        raise ValueError("n must be between 6 and 240")
    distributions = max(2, round((n - 3) / 10))
    accesses = n - 3 - distributions
    mgmt = ipaddress.IPv4Network("10.255.0.0/24")
    vlans = [
        Vlan(id=10, name="STAFF", subnet=ipaddress.IPv4Network("10.10.0.0/20")),
        Vlan(id=99, name="MGMT", subnet=mgmt, management=True),
    ]
    host_ips = vlans[0].subnet.hosts()
    next(host_ips)
    for _ in range(3):  # gateway and the cores' SVI addresses
        next(host_ips)
    devices = [
        Device(
            name="rtr1",
            kind=Kind.ROUTER,
            role="edge",
            model="ISR4331/K9",
            serials=["FDO0000R001"],
            mgmt_ip=ipaddress.IPv4Address("10.254.0.1"),
            loopback=ipaddress.IPv4Address("10.254.0.1"),
        ),
        *(
            Device(
                name=f"core{i}",
                kind=Kind.L3_SWITCH,
                role="core",
                model="C9500-24Y4C",
                serials=[f"FDO0000C00{i}"],
                mgmt_ip=mgmt[1 + i],
                loopback=ipaddress.IPv4Address(f"10.254.0.{1 + i}"),
                stp_priority=24576 if i == 1 else 28672,
                hsrp_active=[10, 99] if i == 1 else [],
            )
            for i in (1, 2)
        ),
    ]
    links = [
        Link.model_validate({"a": "core1 Te1/0/1", "b": "core2 Te1/0/1", "channel": 1}),
        Link.model_validate({"a": "core1 Te1/0/2", "b": "core2 Te1/0/2", "channel": 1}),
        Link.model_validate(
            {"a": "core1 Gi1/0/48", "b": "rtr1 Gi0/0/1", "subnet": "10.254.1.0/30"}
        ),
        Link.model_validate(
            {"a": "core2 Gi1/0/48", "b": "rtr1 Gi0/0/2", "subnet": "10.254.1.4/30"}
        ),
    ]
    for d in range(1, distributions + 1):
        devices.append(
            Device(
                name=f"dist{d}",
                kind=Kind.SWITCH,
                role="distribution",
                model="C9300-24T",
                serials=[f"FOC0000D{d:03d}"],
                mgmt_ip=mgmt[10 + d],
            )
        )
        for core in (1, 2):
            links.append(
                Link.model_validate(
                    {"a": f"core{core} Te1/0/{2 + d}", "b": f"dist{d} Te1/1/{core}"}
                )
            )
    for a in range(1, accesses + 1):
        dist = (a - 1) % distributions + 1
        port = (a - 1) // distributions + 1
        devices.append(
            Device(
                name=f"access{a}",
                kind=Kind.SWITCH,
                role="access",
                model="WS-C2960X-48FPD-L",
                os="ios",
                version="15.2(7)E10",
                serials=[f"FOC0000A{a:03d}"],
                mgmt_ip=mgmt[10 + distributions + a],
                hosts=[Host(port=f"Gi1/0/{h}", vlan=10, ip=next(host_ips)) for h in (1, 2)],
            )
        )
        links.append(
            Link.model_validate({"a": f"dist{dist} Gi1/0/{port}", "b": f"access{a} Gi1/0/49"})
        )
    return Topology(
        name=name or f"synthetic-{n}",
        management_subnet=ipaddress.IPv4Network("10.254.0.0/15"),
        vlans=vlans,
        devices=devices,
        links=links,
    )
