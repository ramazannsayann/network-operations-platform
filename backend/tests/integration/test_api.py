"""The implemented v1 endpoints (devices, discovery runs, jobs) against the test database.

The fake lab is discovered by each test that needs it (fixture ``discovered``); the task
queue is replaced by a recorder, so no broker is needed and nothing runs in the background.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.integration.support import FAKELAB_REQUEST, Recorder

pytestmark = pytest.mark.integration


def devices_by_name(client: TestClient) -> dict[str, dict[str, Any]]:
    page = client.get("/api/v1/devices", params={"limit": 500}).json()
    return {d["hostname"]: d for d in page["items"]}


def test_discovery_run_and_its_job(discovered: tuple[TestClient, Recorder, dict[str, Any]]) -> None:
    client, _, job_ref = discovered

    job = client.get(job_ref["href"]).json()
    assert job["status"] == "succeeded"
    assert job["kind"] == "discovery"
    assert job["error"] is None
    assert job["progress"]["completed"] == job["progress"]["total"] == 11

    runs = client.get("/api/v1/discovery/runs").json()
    assert runs["total"] == 1
    (summary,) = runs["items"]
    assert summary["status"] == "succeeded"
    assert summary["progress"] == {
        "queued": 0,
        "scanned": 10,
        "found": 8,
        "skipped": 2,
        "errors": 1,
    }

    detail = client.get(job["target_href"]).json()
    assert detail["request"]["seeds"] == ["10.255.0.2"]
    assert detail["request"]["allowed_subnets"] == ["10.255.0.0/24"]
    assert len(detail["found_devices"]) == 8
    assert {
        d["device"]["hostname"] for d in detail["found_devices"] if d["discovered_via"] == "seed"
    } == {"core1"}
    skipped = {s["name"]: s for s in detail["skipped_neighbors"]}
    assert skipped["isp-ce1"]["reason"] == "out_of_scope"
    assert skipped["isp-ce1"]["seen_from"]["hostname"] == "rtr1"
    assert skipped["isp-ce1"]["local_interface"] == "GigabitEthernet0/0/0"
    assert skipped["ap1"]["reason"] == "unsupported_platform"
    assert skipped["access4.lab.example.net"]["reason"] == "auth_failed"
    (error,) = detail["errors"]
    assert error["target"] == "10.255.0.74"
    assert "authentication failed" in error["message"]

    assert client.get("/api/v1/discovery/runs?status=running").json()["total"] == 0
    missing = client.get(f"/api/v1/discovery/runs/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.headers["content-type"] == "application/problem+json"


def test_device_list_detail_and_interfaces(
    discovered: tuple[TestClient, Recorder, dict[str, Any]],
) -> None:
    client, _, _ = discovered
    devices = devices_by_name(client)
    assert len(devices) == 11
    assert devices["isp-ce1"]["management_status"] == "out_of_scope"
    assert devices["dist2"]["serials"] == ["FOC1111D002", "FOC1111D003"]
    assert devices["core1"]["role"] == "core"

    managed = client.get("/api/v1/devices", params={"management_status": "managed"}).json()
    assert managed["total"] == 8
    by_serial = client.get("/api/v1/devices", params={"q": "foc1111d003"}).json()
    assert [d["hostname"] for d in by_serial["items"]] == ["dist2"]
    by_ip = client.get("/api/v1/devices", params={"q": "10.255.0.12"}).json()
    assert [d["hostname"] for d in by_ip["items"]] == ["dist2", "rtr1"]  # substring: .129
    routers = client.get("/api/v1/devices", params={"device_type": "router"}).json()
    assert {d["hostname"] for d in routers["items"]} == {"rtr1", "isp-ce1"}
    page = client.get("/api/v1/devices", params={"sort": "-hostname", "limit": 2}).json()
    assert [d["hostname"] for d in page["items"]] == ["rtr1", "isp-ce1"]
    assert page["total"] == 11

    dist2 = client.get(f"/api/v1/devices/{devices['dist2']['id']}").json()
    assert [(s["serial"], s["stack_member"]) for s in dist2["serial_details"]] == [
        ("FOC1111D002", 1),
        ("FOC1111D003", 2),
    ]
    assert dist2["interface_count"] > 0
    kinds = {c["kind"]: c["last_status"] for c in dist2["collections"]}
    assert kinds == dict.fromkeys(
        ["facts", "interfaces", "neighbors", "vlans", "mac_table", "arp_table", "stp"], "success"
    )
    assert client.get(f"/api/v1/devices/{uuid.uuid4()}").status_code == 404

    core1 = devices["core1"]["id"]
    channels = client.get(
        f"/api/v1/devices/{core1}/interfaces", params={"kind": "port_channel"}
    ).json()
    (po1,) = channels["items"]
    assert po1["name_normalized"] == "Port-channel1"
    assert po1["state"]["switchport_mode"] == "trunk"
    members = client.get(f"/api/v1/devices/{core1}/interfaces", params={"limit": 500}).json()
    parents = {i["name_normalized"]: i["parent_interface_id"] for i in members["items"]}
    assert parents["TenGigabitEthernet1/1/1"] == parents["TenGigabitEthernet1/1/2"] == po1["id"]
    down = client.get(f"/api/v1/devices/{core1}/interfaces", params={"oper_up": False}).json()
    assert down["total"] == 0
    past = client.get(
        f"/api/v1/devices/{core1}/interfaces", params={"at": "2020-01-01T00:00:00Z"}
    ).json()
    assert past["total"] == 0


def test_refresh_creates_a_job_and_enqueues_collection(
    discovered: tuple[TestClient, Recorder, dict[str, Any]],
) -> None:
    client, recorder, _ = discovered
    devices = devices_by_name(client)
    core1 = devices["core1"]["id"]

    response = client.post(f"/api/v1/devices/{core1}/refresh", json={"kinds": ["mac_table"]})
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["kind"] == "device_refresh"
    assert job["target_href"] == f"/api/v1/devices/{core1}"
    assert recorder.calls[-1] == (
        "netops.collect_device",
        (core1, ["mac_table"], "manual", job["id"]),
    )
    queued = client.get(job["href"]).json()
    assert queued["status"] == "queued"
    assert queued["progress"] is None

    isp = devices["isp-ce1"]["id"]
    assert client.post(f"/api/v1/devices/{isp}/refresh").status_code == 409
    assert client.post(f"/api/v1/devices/{uuid.uuid4()}/refresh").status_code == 404
    assert client.get(f"/api/v1/jobs/{uuid.uuid4()}").status_code == 404


def test_discovery_requests_are_validated(
    api: tuple[TestClient, Recorder], profiles: list[uuid.UUID]
) -> None:
    client, recorder = api
    unknown = client.post(
        "/api/v1/discovery/runs",
        json=FAKELAB_REQUEST | {"credential_profile_ids": [str(uuid.uuid4())]},
    )
    assert unknown.status_code == 422
    assert unknown.headers["content-type"] == "application/problem+json"

    body = FAKELAB_REQUEST | {"credential_profile_ids": [str(profiles[1])]}
    assert client.post("/api/v1/discovery/runs", json=body).status_code == 202
    conflict = client.post("/api/v1/discovery/runs", json=body)
    assert conflict.status_code == 409  # the first run is still queued
    assert len(recorder.calls) == 1
