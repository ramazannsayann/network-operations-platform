"""Discovery end to end: the fake lab (lab/fakelab/topology.yaml) served on 127.0.0.1 ->
BFS from one seed -> test database. The connection-target resolver maps each management
address to its fake device; scope checks and everything stored use the real addresses."""

import asyncio
import ipaddress
import secrets
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netops.core.secrets import Secret
from netops.core.settings import get_settings
from netops.db import models as m
from netops.db.enums import (
    CollectionStatus,
    CredentialKind,
    DeviceRole,
    DeviceType,
    DiscoveryItemStatus,
    JobStatus,
    ManagementStatus,
)
from netops.discovery.engine import run_discovery
from netops.discovery.service import (
    CredentialProfileError,
    DiscoveryInProgressError,
    request_discovery,
)
from netops_fakes.accuracy import evaluate
from netops_fakes.local import LocalLab
from netops_fakes.topology import Topology, load
from tests.integration.support import clear_inventory, run

pytestmark = pytest.mark.integration

TOPOLOGY = Path(__file__).resolve().parents[3] / "lab" / "fakelab" / "topology.yaml"
ALLOWED = ipaddress.ip_network("10.255.0.0/24")
SEED = ipaddress.ip_address("10.255.0.2")  # core1
USERNAME = "netops-ro"
PASSWORD = "pw-" + secrets.token_hex(8)  # random per run: no password literal in the repo
OUTDATED = "pw-" + secrets.token_hex(8)  # a profile tried first that no device accepts


@pytest.fixture
def profiles(app_on_test_database: None) -> Iterator[list[uuid.UUID]]:
    """An empty inventory and two SSH profiles: an outdated one first, then the lab's."""

    async def create(session: AsyncSession) -> list[uuid.UUID]:
        await clear_inventory(session)
        rows = [
            m.CredentialProfile(
                id=uuid.uuid4(),
                name=name,
                kind=CredentialKind.SSH,
                username=USERNAME,
                password=Secret(password),
            )
            for name, password in (("lab-outdated", OUTDATED), ("lab", PASSWORD))
        ]
        session.add_all(rows)
        await session.commit()
        return [row.id for row in rows]

    yield run(create)
    run(clear_inventory)


def discover(lab: LocalLab, profile_ids: list[uuid.UUID]) -> uuid.UUID:
    async def request(session: AsyncSession) -> uuid.UUID:
        discovery_run, _ = await request_discovery(session, [SEED], [ALLOWED], profile_ids)
        return discovery_run.id

    run_id = run(request)
    status = asyncio.run(run_discovery(run_id, get_settings(), lab.resolve))
    assert status is JobStatus.SUCCEEDED
    return run_id


@dataclass
class Inventory:
    devices: dict[str, m.Device]
    serials: dict[str, list[str]]
    active_links: set[frozenset[tuple[str, str]]]
    inactive_links: set[frozenset[tuple[str, str]]]
    parents: dict[tuple[str, str], str | None]  # (device, interface) -> port-channel
    items: list[m.DiscoveryRunItem]
    discovery_run: m.DiscoveryRun


def inventory(run_id: uuid.UUID) -> Inventory:
    async def load_state(session: AsyncSession) -> Inventory:
        devices = list(await session.scalars(select(m.Device)))
        names = {d.id: d.hostname or str(d.mgmt_ip) for d in devices}
        serials: dict[str, list[str]] = {}
        for serial in await session.scalars(select(m.DeviceSerial)):
            serials.setdefault(names[serial.device_id], []).append(serial.serial)
        interfaces = {i.id: i for i in await session.scalars(select(m.Interface))}
        parents = {
            (names[i.device_id], i.name_normalized): (
                interfaces[i.parent_interface_id].name_normalized if i.parent_interface_id else None
            )
            for i in interfaces.values()
        }
        links: dict[bool, set[frozenset[tuple[str, str]]]] = {True: set(), False: set()}
        for link in await session.scalars(select(m.Link)):
            ends = [interfaces[link.a_interface_id], interfaces[link.b_interface_id]]
            links[link.is_active].add(
                frozenset((names[i.device_id], i.name_normalized) for i in ends)
            )
        items = list(
            await session.scalars(
                select(m.DiscoveryRunItem)
                .where(m.DiscoveryRunItem.run_id == run_id)
                .order_by(m.DiscoveryRunItem.id)
            )
        )
        discovery_run = await session.get(m.DiscoveryRun, run_id)
        assert discovery_run is not None
        return Inventory(
            devices={names[d.id]: d for d in devices},
            serials=serials,
            active_links=links[True],
            inactive_links=links[False],
            parents=parents,
            items=items,
            discovery_run=discovery_run,
        )

    return run(load_state)


def topology_links(topology: Topology) -> set[frozenset[tuple[str, str]]]:
    return {
        frozenset({(link.a.device, link.a.port), (link.b.device, link.b.port)})
        for link in topology.links
    }


def test_discover_the_whole_fake_lab_from_one_seed(profiles: list[uuid.UUID]) -> None:
    topology = load(TOPOLOGY)
    with LocalLab(topology, USERNAME, PASSWORD) as lab:
        started = time.perf_counter()
        run_id = discover(lab, profiles)
        duration = time.perf_counter() - started
        state = inventory(run_id)

        # Every device of the topology exists exactly once, placeholders included.
        assert sorted(state.devices) == sorted(d.name for d in topology.devices)
        assert state.active_links == topology_links(topology)
        assert not state.inactive_links

        # The provider router is out of scope and was never connected to.
        isp = state.devices["isp-ce1"]
        assert isp.management_status is ManagementStatus.OUT_OF_SCOPE
        assert not isp.is_managed
        assert str(isp.mgmt_ip) == "198.51.100.1"
        assert "198.51.100.1" not in lab.connections
        assert all(ipaddress.ip_address(a) in ALLOWED for a in lab.connections)

        # Wrong credentials: two attempts (one per profile), then auth_failed.
        access4 = state.devices["access4"]
        assert access4.management_status is ManagementStatus.AUTH_FAILED
        (item,) = [i for i in state.items if str(i.address) == "10.255.0.74"]
        assert item.status is DiscoveryItemStatus.AUTH_FAILED
        assert item.attempts == 2
        assert lab.devices["access4"].failed_logins == 2
        assert lab.devices["access4"].sessions == 0

        # The AP is recorded from CDP but not logged in to.
        assert state.devices["ap1"].management_status is ManagementStatus.UNSUPPORTED_PLATFORM
        assert state.devices["ap1"].device_type is DeviceType.AP
        assert "10.255.0.40" not in lab.connections

        # The stack exists once, with both serials; its second address is a duplicate.
        assert sorted(state.serials["dist2"]) == ["FOC1111D002", "FOC1111D003"]
        assert str(state.devices["dist2"].mgmt_ip) == "10.255.0.12"
        duplicates = [i for i in state.items if i.status is DiscoveryItemStatus.DUPLICATE]
        assert [str(i.address) for i in duplicates] == ["10.255.0.70"]
        assert duplicates[0].device_id == state.devices["dist2"].id

        # EtherChannel: two physical links, each between members of Port-channel1.
        channel_links = {
            link
            for link in state.active_links
            if {device for device, _ in link} == {"core1", "core2"}
        }
        assert len(channel_links) == 2
        for link in channel_links:
            assert {state.parents[end] for end in link} == {"Port-channel1"}

        # Device types, roles, remembered credentials, command sets per type.
        lab_profile = profiles[1]
        for device in topology.devices:
            found = state.devices[device.name]
            if not device.external and device.credentials == "lab":
                assert found.management_status is ManagementStatus.MANAGED
                assert found.credential_profile_id == lab_profile
            if device.role != "unknown":
                assert found.role is DeviceRole(device.role), device.name
        assert state.devices["rtr1"].device_type is DeviceType.ROUTER
        assert state.devices["core1"].device_type is DeviceType.L3_SWITCH
        assert state.devices["access1"].device_type is DeviceType.SWITCH
        assert run(lambda s: _run_statuses(s, state.devices["rtr1"].id)) == {
            CollectionStatus.SUCCESS
        }
        assert run(lambda s: _run_statuses(s, state.devices["dist2"].id)) == {
            CollectionStatus.SUCCESS
        }

        counters = state.discovery_run
        assert counters.found == 8  # rtr1, core1-2, dist1-2, access1-3
        assert counters.new_devices == 8
        assert counters.errors == 1  # access4
        assert counters.skipped == 2  # isp-ce1, ap1

        accuracy = run(lambda session: evaluate(session, topology))
        print(f"\nfake lab discovery: {duration:.1f} s\n{accuracy.report()}")  # noqa: T201
        assert accuracy.perfect
        assert accuracy.roles.matched == accuracy.roles.expected


async def _run_statuses(session: AsyncSession, device_id: uuid.UUID) -> set[CollectionStatus]:
    rows = await session.scalars(
        select(m.CollectionRun.status).where(m.CollectionRun.device_id == device_id)
    )
    return set(rows)


def test_rediscovery_converges_and_detects_removed_links(profiles: list[uuid.UUID]) -> None:
    topology = load(TOPOLOGY)
    with LocalLab(topology, USERNAME, PASSWORD) as lab:
        first = inventory(discover(lab, profiles))
        failed_before = {name: d.failed_logins for name, d in lab.devices.items()}
        second = inventory(discover(lab, profiles))

        # No duplicates: the same devices (same ids) and links.
        assert {n: d.id for n, d in second.devices.items()} == {
            n: d.id for n, d in first.devices.items()
        }
        assert second.active_links == first.active_links
        assert second.discovery_run.new_devices == 0
        # The profile that worked is tried first now: no more failed logins, except on the
        # switch nobody has the password for.
        failed_now = {
            name: d.failed_logins - failed_before[name] for name, d in lab.devices.items()
        }
        assert {name: n for name, n in failed_now.items() if n} == {"access4": 2}

    # core2 <-> dist1 is unplugged; dist1 stays reachable via core1.
    removed = next(
        link for link in topology.links if {link.a.device, link.b.device} == {"core2", "dist1"}
    )
    changed = topology.model_copy(
        update={"links": [link for link in topology.links if link != removed]}
    )
    with LocalLab(changed, USERNAME, PASSWORD) as lab:
        third = inventory(discover(lab, profiles))
    gone = frozenset({(removed.a.device, removed.a.port), (removed.b.device, removed.b.port)})
    assert third.inactive_links == {gone}
    assert third.active_links == first.active_links - {gone}
    assert sorted(third.devices) == sorted(first.devices)


def test_discovery_requests_are_checked(profiles: list[uuid.UUID]) -> None:
    async def twice(session: AsyncSession) -> None:
        await request_discovery(session, [SEED], [ALLOWED], profiles)
        with pytest.raises(DiscoveryInProgressError):
            await request_discovery(session, [SEED], [ALLOWED], profiles)
        with pytest.raises(CredentialProfileError):
            await request_discovery(session, [SEED], [ALLOWED], [uuid.uuid4()])

    run(twice)
