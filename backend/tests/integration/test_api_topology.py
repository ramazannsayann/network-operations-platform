"""Topology, credential profile and map layout endpoints against the discovered fake lab."""

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from netops.core.settings import get_settings
from netops.db import models as m
from netops.db.enums import DiscoverySource
from netops.discovery.engine import run_discovery
from netops_fakes.local import LocalLab
from netops_fakes.topology import load
from tests.integration.support import (
    FAKELAB_REQUEST,
    FAKELAB_TOPOLOGY,
    OUTDATED,
    PASSWORD,
    USERNAME,
    Recorder,
    run,
)

pytestmark = pytest.mark.integration

Discovered = tuple[TestClient, Recorder, dict[str, Any]]


def topology(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get("/api/v1/topology", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def names(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["label"]: node for node in graph["nodes"]}


def edge_between(graph: dict[str, Any], a: str, b: str) -> list[dict[str, Any]]:
    ids = {node["label"]: node["id"] for node in graph["nodes"]}
    return [e for e in graph["edges"] if {e["source"], e["target"]} == {ids[a], ids[b]}]


def test_l2_topology_collapses_etherchannels_and_flags_unmanaged_nodes(
    discovered: Discovered,
) -> None:
    client, _, _ = discovered
    graph = topology(client)
    assert graph["layer"] == "l2"
    nodes = names(graph)
    assert len(nodes) == 11
    # 14 cables, the two core1-core2 members collapsed into one logical edge.
    assert len(graph["edges"]) == 13

    assert nodes["isp-ce1"]["out_of_scope"] is True
    assert nodes["isp-ce1"]["management_status"] == "out_of_scope"
    assert nodes["isp-ce1"]["is_managed"] is False
    assert nodes["ap1"]["management_status"] == "unsupported_platform"
    assert nodes["ap1"]["device_type"] == "ap"
    assert nodes["access4"]["management_status"] == "auth_failed"
    assert nodes["core1"]["management_status"] == "managed"
    assert nodes["core1"]["role"] == "core"
    assert nodes["core1"]["mgmt_ip"] == "10.255.0.2"
    assert nodes["core1"]["open_alarm_count"] == 0

    (channel,) = edge_between(graph, "core1", "core2")
    assert channel["kind"] == "etherchannel"
    assert channel["source_interface"]["name"] == "Port-channel1"
    assert channel["target_interface"]["name"] == "Port-channel1"
    assert channel["link_id"] is None
    assert [
        (m["source_interface"]["name"], m["target_interface"]["name"], m["is_active"])
        for m in channel["members"]
    ] == [
        ("TenGigabitEthernet1/1/1", "TenGigabitEthernet1/1/1", True),
        ("TenGigabitEthernet1/1/2", "TenGigabitEthernet1/1/2", True),
    ]

    (uplink,) = edge_between(graph, "dist1", "access1")
    assert uplink["kind"] == "link"
    assert uplink["members"] == []
    assert uplink["link_id"] == uplink["id"]
    assert {uplink["source_interface"]["name"], uplink["target_interface"]["name"]} == {
        "GigabitEthernet1/0/1",
        "GigabitEthernet1/0/49",
    }
    (provider,) = edge_between(graph, "rtr1", "isp-ce1")
    assert provider["link_source"] == "cdp"

    access_only = topology(client, role="access")
    assert {n["label"] for n in access_only["nodes"]} == {
        "access1",
        "access2",
        "access3",
        "access4",
    }
    assert access_only["edges"] == []  # no access-to-access links


def test_l3_topology_shows_subnets_and_hsrp(discovered: Discovered) -> None:
    client, _, _ = discovered
    graph = topology(client, layer="l3")
    nodes = names(graph)
    devices = {label for label, n in nodes.items() if n["kind"] == "device"}
    subnets = {label: n for label, n in nodes.items() if n["kind"] == "subnet"}
    assert devices == {"rtr1", "core1", "core2", "isp-ce1"}
    assert set(subnets) == {
        "10.10.10.0/24",
        "10.10.20.0/24",
        "10.255.0.0/27",
        "10.255.0.32/27",
        "10.255.0.64/26",
        "10.255.0.192/30",
        "10.255.0.196/30",
        "198.51.100.0/30",
    }  # loopbacks (/32) are not subnets
    assert subnets["10.10.10.0/24"]["gateway_ips"] == ["10.10.10.1"]
    assert subnets["10.255.0.192/30"]["gateway_ips"] == []
    assert len(graph["edges"]) == 16

    def member(device: str, subnet: str) -> dict[str, Any]:
        (edge,) = edge_between(graph, device, subnet)
        assert edge["kind"] == "subnet_member"
        return edge

    assert member("core1", "10.10.10.0/24")["hsrp_state"] == "active"
    assert member("core2", "10.10.10.0/24")["hsrp_state"] == "standby"
    assert member("core2", "10.10.20.0/24")["hsrp_state"] == "active"
    assert member("core1", "10.10.10.0/24")["address"] == "10.10.10.2/24"
    assert member("core1", "10.10.10.0/24")["source_interface"]["name"] == "Vlan10"
    assert member("rtr1", "10.255.0.192/30")["hsrp_state"] is None
    # The provider router has no collected addresses; it joins via its management address.
    provider = member("isp-ce1", "198.51.100.0/30")
    assert provider["address"] == "198.51.100.1/30"
    assert provider["source_interface"] is None


def test_time_travel_and_changes(discovered: Discovered, profiles: list[uuid.UUID]) -> None:
    client, recorder, _ = discovered
    before = "2020-01-01T00:00:00Z"
    assert topology(client, at=before)["nodes"] == []
    time.sleep(1.1)
    after_first = datetime.now(UTC)
    time.sleep(1.1)

    # core2 <-> dist1 is unplugged and the lab discovered again.
    lab_topology = load(FAKELAB_TOPOLOGY)
    removed = next(
        link for link in lab_topology.links if {link.a.device, link.b.device} == {"core2", "dist1"}
    )
    changed = lab_topology.model_copy(
        update={"links": [link for link in lab_topology.links if link != removed]}
    )
    response = client.post(
        "/api/v1/discovery/runs",
        json=FAKELAB_REQUEST | {"credential_profile_ids": [str(p) for p in profiles]},
    )
    assert response.status_code == 202, response.text
    run_id = recorder.calls[-1][1][0]
    with LocalLab(changed, USERNAME, PASSWORD) as lab:
        asyncio.run(run_discovery(uuid.UUID(run_id), get_settings(), lab.resolve))

    now = topology(client)
    assert len(now["edges"]) == 12
    assert edge_between(now, "core2", "dist1") == []
    then = topology(client, at=after_first.isoformat())
    assert len(then["edges"]) == 13
    assert len(edge_between(then, "core2", "dist1")) == 1
    assert len(then["nodes"]) == 11

    changes = client.get("/api/v1/topology/changes", params={"since": before}).json()
    assert len(changes["added_devices"]) == 11
    assert len(changes["added_links"]) == 14
    assert changes["removed_devices"] == []
    (gone,) = changes["removed_links"]
    assert {gone["a"]["device"]["hostname"], gone["b"]["device"]["hostname"]} == {
        "core2",
        "dist1",
    }
    since_rerun = client.get(
        "/api/v1/topology/changes", params={"since": after_first.isoformat()}
    ).json()
    assert since_rerun["added_devices"] == []
    assert since_rerun["added_links"] == []
    assert len(since_rerun["removed_links"]) == 1
    bad = client.get(
        "/api/v1/topology/changes",
        params={"since": "2030-01-01T00:00:00Z", "until": "2029-01-01T00:00:00Z"},
    )
    assert bad.status_code == 422


def test_credential_profiles_never_expose_secrets(api: tuple[TestClient, Recorder]) -> None:
    client, _ = api
    response = client.get("/api/v1/credential-profiles")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [(p["name"], p["kind"]) for p in body["items"]] == [
        ("lab", "ssh"),
        ("lab-outdated", "ssh"),
    ]
    assert all(set(p) == {"id", "name", "kind"} for p in body["items"])
    text = json.dumps(body)
    for secret in (PASSWORD, OUTDATED, USERNAME):
        assert secret not in text
    filtered = client.get("/api/v1/credential-profiles", params={"kind": "snmpv3"}).json()
    assert filtered["total"] == 0


def test_layout_is_saved_validated_and_reset(discovered: Discovered) -> None:
    client, _, _ = discovered
    ids = {n["label"]: n["id"] for n in topology(client)["nodes"]}
    empty = client.get("/api/v1/topology/layout").json()
    assert empty == {"layer": "l2", "positions": [], "updated_at": None}

    body = {
        "positions": [
            {"node_id": ids["core1"], "x": 100.5, "y": 20},
            {"node_id": ids["access1"], "x": -40, "y": 300},
        ]
    }
    saved = client.put("/api/v1/topology/layout", json=body)
    assert saved.status_code == 200, saved.text
    layout = client.get("/api/v1/topology/layout").json()
    assert {(p["node_id"], p["x"], p["y"]) for p in layout["positions"]} == {
        (ids["core1"], 100.5, 20.0),
        (ids["access1"], -40.0, 300.0),
    }
    assert layout["updated_at"] is not None
    assert client.get("/api/v1/topology/layout", params={"layer": "l3"}).json()["positions"] == []

    unknown = {"positions": [{"node_id": str(uuid.uuid4()), "x": 0, "y": 0}]}
    assert client.put("/api/v1/topology/layout", json=unknown).status_code == 422
    subnet = {"positions": [{"node_id": "10.10.10.0/24", "x": 1, "y": 2}]}
    assert client.put("/api/v1/topology/layout", json=subnet).status_code == 422  # not on L2
    l3 = client.put("/api/v1/topology/layout", params={"layer": "l3"}, json=subnet)
    assert l3.status_code == 200, l3.text
    assert (
        client.put(
            "/api/v1/topology/layout", json={"positions": [{"node_id": "x", "x": 1e9, "y": 0}]}
        ).status_code
        == 422
    )  # out of range

    reset = client.put("/api/v1/topology/layout", json={"positions": []}).json()
    assert reset["positions"] == []
    assert client.get("/api/v1/topology/layout", params={"layer": "l3"}).json()["positions"]


def test_locations_are_listed_with_paths_and_device_counts(
    api: tuple[TestClient, Recorder],
) -> None:
    client, _ = api
    assert client.get("/api/v1/locations").json()["total"] == 0

    async def create(session: AsyncSession) -> None:
        campus = m.Location(id=uuid.uuid4(), name="Campus")
        block = m.Location(id=uuid.uuid4(), name="B Block", parent_id=campus.id)
        session.add(campus)
        await session.flush()
        session.add(block)
        await session.flush()
        session.add(
            m.Device(
                id=uuid.uuid4(),
                hostname="sw-test",
                discovered_via=DiscoverySource.MANUAL,
                location_id=block.id,
            )
        )
        await session.commit()

    run(create)
    page = client.get("/api/v1/locations").json()
    assert [(loc["path"], loc["device_count"]) for loc in page["items"]] == [
        ("Campus", 0),
        ("Campus / B Block", 1),
    ]
    found = client.get("/api/v1/locations", params={"q": "block"}).json()
    assert [loc["name"] for loc in found["items"]] == ["B Block"]
