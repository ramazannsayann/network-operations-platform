"""Discovery's pure parts: command sets per device type, classification, roles."""

import uuid

import pytest

from netops.db.enums import (
    CollectionKind,
    DeviceRole,
    DeviceType,
    NeighborProtocol,
    OsFamily,
    RouteProtocol,
)
from netops.discovery import classify
from netops.discovery.roles import derive_roles
from netops.inventory.collectors import DEFAULT_KINDS, commands_for, kinds_for
from netops.parsing.models import Facts, Neighbor, Route


def test_routers_skip_switch_only_commands_and_kinds() -> None:
    assert CollectionKind.VLANS not in kinds_for(DeviceType.ROUTER)
    assert CollectionKind.STP not in kinds_for(DeviceType.ROUTER)
    assert commands_for(CollectionKind.INTERFACES, DeviceType.ROUTER) == ("show interfaces",)
    assert "show etherchannel summary" in commands_for(CollectionKind.INTERFACES, DeviceType.SWITCH)
    assert CollectionKind.ROUTES not in kinds_for(DeviceType.SWITCH)
    assert kinds_for(DeviceType.L3_SWITCH) == DEFAULT_KINDS
    assert kinds_for(DeviceType.UNKNOWN) == DEFAULT_KINDS


def _facts(model: str) -> Facts:
    return Facts("x", OsFamily.IOSXE, "17.9.4a", model, ("FOC1",), None)


ROUTE = Route("10.0.0.0/24", RouteProtocol.CONNECTED, None, "Vlan10", None, None, None)


@pytest.mark.parametrize(
    ("model", "routes", "expected"),
    [
        ("ISR4331/K9", [ROUTE], DeviceType.ROUTER),
        ("C8300-1N1S-4T2X", None, DeviceType.ROUTER),
        ("C9300-48T", [ROUTE], DeviceType.L3_SWITCH),
        ("C9300-48T", [], DeviceType.SWITCH),  # "Default gateway is ..."
        ("WS-C2960X-48FPD-L", None, DeviceType.SWITCH),
    ],
)
def test_device_type(model: str, routes: list[Route] | None, expected: DeviceType) -> None:
    assert classify.device_type(_facts(model), routes) is expected


def _neighbor(platform: str, *capabilities: str) -> Neighbor:
    return Neighbor(
        NeighborProtocol.CDP, "Gi1/0/1", "n", "10.0.0.9", "Gi0/1", platform, capabilities
    )


def test_neighbor_support_and_type() -> None:
    switch = _neighbor("cisco WS-C2960X-48FPD-L", "Switch", "IGMP")
    ap = _neighbor("cisco AIR-AP2802I-E-K9", "Trans-Bridge", "Source-Route-Bridge", "IGMP")
    phone = _neighbor("Cisco IP Phone 8845", "Host", "Phone")
    isp = _neighbor("cisco ISR4451-X/K9", "Router", "Source-Route-Bridge")
    linux = _neighbor("Linux", "Router", "Switch")
    assert classify.is_supported(switch)
    assert classify.is_supported(isp)
    assert not classify.is_supported(ap)
    assert not classify.is_supported(phone)
    assert not classify.is_supported(linux)
    assert classify.neighbor_type(ap) is DeviceType.AP
    assert classify.neighbor_type(isp) is DeviceType.ROUTER
    assert classify.neighbor_type(_neighbor("cisco C9300", "Router", "Switch")) is (
        DeviceType.L3_SWITCH
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("core1.lab.example.net", "core1"),
        ("ap1", "ap1"),
        ("nx1(FOX1234ABCD)", "nx1"),
        ("10.0.0.1", "10.0.0.1"),
        (None, None),
    ],
)
def test_short_name(name: str | None, expected: str | None) -> None:
    assert classify.short_name(name) == expected


def test_serial_and_model_from_neighbor_reports() -> None:
    assert classify.serial_in_name("nx1(FOX1234ABCD)") == "FOX1234ABCD"
    assert classify.serial_in_name("core1.lab.example.net") is None
    assert classify.model_from_platform("cisco WS-C2960X-48FPD-L") == "WS-C2960X-48FPD-L"
    assert classify.model_from_platform("Linux") is None


def test_role_heuristic_on_a_small_campus() -> None:
    ids = {name: uuid.uuid4() for name in ("rtr", "c1", "c2", "d1", "a1", "a2", "lonely")}
    types = {
        ids["rtr"]: DeviceType.ROUTER,
        ids["c1"]: DeviceType.L3_SWITCH,
        ids["c2"]: DeviceType.L3_SWITCH,
        ids["d1"]: DeviceType.SWITCH,
        ids["a1"]: DeviceType.SWITCH,
        ids["a2"]: DeviceType.SWITCH,
        ids["lonely"]: DeviceType.SWITCH,
    }
    edges = [("rtr", "c1"), ("rtr", "c2"), ("c1", "c2"), ("c1", "d1"), ("c2", "d1"), ("d1", "a1")]
    edges.append(("d1", "a2"))
    adjacency: dict[uuid.UUID, set[uuid.UUID]] = {}
    for a, b in edges:
        adjacency.setdefault(ids[a], set()).add(ids[b])
        adjacency.setdefault(ids[b], set()).add(ids[a])
    roles = {name: derive_roles(types, adjacency)[ids[name]] for name in ids}
    assert roles == {
        "rtr": DeviceRole.EDGE,
        "c1": DeviceRole.CORE,
        "c2": DeviceRole.CORE,
        "d1": DeviceRole.DISTRIBUTION,
        "a1": DeviceRole.ACCESS,
        "a2": DeviceRole.ACCESS,
        "lonely": DeviceRole.UNKNOWN,
    }


def test_without_a_router_the_best_connected_l3_switch_is_core() -> None:
    core, dist, access = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    types = {core: DeviceType.L3_SWITCH, dist: DeviceType.L3_SWITCH, access: DeviceType.SWITCH}
    adjacency = {core: {dist, access}, dist: {core}, access: {core}}
    roles = derive_roles(types, adjacency)
    assert roles[core] is DeviceRole.CORE
    assert roles[access] is DeviceRole.ACCESS
