"""Database-enforced rules of the data model (ADR-0002) against a real database."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from netops.db.enums import (
    AlarmState,
    CollectionKind,
    CollectionStatus,
    CollectionTrigger,
    DiscoverySource,
    LinkSource,
    MacEntryType,
    Severity,
)
from netops.db.models import Alarm, CollectionRun, Device, Interface, Link, MacEntry

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

T0 = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


async def add_device(session: AsyncSession, hostname: str = "sw1") -> Device:
    device = Device(hostname=hostname, discovered_via=DiscoverySource.SEED)
    session.add(device)
    await session.flush()
    return device


async def add_interface(session: AsyncSession, device: Device, name: str) -> Interface:
    interface = Interface(device_id=device.id, name=name, name_normalized=name)
    session.add(interface)
    await session.flush()
    return interface


async def add_mac_run(session: AsyncSession, device: Device) -> CollectionRun:
    run = CollectionRun(
        device_id=device.id,
        kind=CollectionKind.MAC_TABLE,
        trigger=CollectionTrigger.SCHEDULED,
        status=CollectionStatus.SUCCESS,
        started_at=T0,
        finished_at=T0 + timedelta(seconds=5),
    )
    session.add(run)
    await session.flush()
    return run


async def expect_integrity_error(session: AsyncSession, *rows: object) -> None:
    """Adding ``rows`` must fail; the savepoint keeps the rest of the test's data intact."""
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add_all(rows)


def mac_entry(run: CollectionRun, **overrides: object) -> MacEntry:
    values: dict[str, object] = {
        "collected_at": run.started_at,
        "run_id": run.id,
        "device_id": run.device_id,
        "vlan_id": 10,
        "mac": "aa:bb:cc:00:00:01",
        "entry_type": MacEntryType.DYNAMIC,
    }
    values.update(overrides)
    return MacEntry(**values)


async def test_observation_must_carry_its_runs_time_and_device(session: AsyncSession) -> None:
    sw1, sw2 = await add_device(session, "sw1"), await add_device(session, "sw2")
    run = await add_mac_run(session, sw1)

    session.add(mac_entry(run))
    await session.flush()
    await expect_integrity_error(session, mac_entry(run, collected_at=T0 + timedelta(seconds=1)))
    await expect_integrity_error(session, mac_entry(run, device_id=sw2.id))


async def test_observation_rows_are_unique_within_a_run(session: AsyncSession) -> None:
    run = await add_mac_run(session, await add_device(session))
    session.add(mac_entry(run))
    await session.flush()
    await expect_integrity_error(session, mac_entry(run))


async def test_deleting_a_device_cascades_into_hypertables(session: AsyncSession) -> None:
    device = await add_device(session)
    run = await add_mac_run(session, device)
    session.add(mac_entry(run))
    await session.flush()

    await session.delete(device)
    await session.flush()
    assert await session.scalar(select(func.count()).select_from(MacEntry)) == 0
    assert await session.scalar(select(func.count()).select_from(CollectionRun)) == 0


async def test_host_address_columns_reject_prefixes(session: AsyncSession) -> None:
    await expect_integrity_error(
        session, Device(mgmt_ip="10.0.0.1/24", discovered_via=DiscoverySource.MANUAL)
    )
    session.add(Device(mgmt_ip="10.0.0.1", discovered_via=DiscoverySource.MANUAL))
    await session.flush()


async def test_interface_names_are_unique_per_device_after_normalization(
    session: AsyncSession,
) -> None:
    sw1, sw2 = await add_device(session, "sw1"), await add_device(session, "sw2")
    await add_interface(session, sw1, "GigabitEthernet1/0/1")
    await add_interface(session, sw2, "GigabitEthernet1/0/1")
    await expect_integrity_error(
        session, Interface(device_id=sw1.id, name="Gi1/0/1", name_normalized="GigabitEthernet1/0/1")
    )


async def test_links_are_stored_once_with_ordered_endpoints(session: AsyncSession) -> None:
    device = await add_device(session)
    one = await add_interface(session, device, "Gi1/0/1")
    two = await add_interface(session, device, "Gi1/0/2")
    first, second = sorted([one, two], key=lambda interface: interface.id)
    session.add(Link(a_interface_id=first.id, b_interface_id=second.id, source=LinkSource.CDP))
    await session.flush()
    await expect_integrity_error(
        session, Link(a_interface_id=second.id, b_interface_id=first.id, source=LinkSource.LLDP)
    )
    await expect_integrity_error(
        session, Link(a_interface_id=first.id, b_interface_id=second.id, source=LinkSource.LLDP)
    )


async def test_only_one_live_alarm_per_dedup_key(session: AsyncSession) -> None:
    device = await add_device(session)

    def alarm(state: AlarmState = AlarmState.OPEN) -> Alarm:
        return Alarm(
            device_id=device.id,
            rule_key="interface.down",
            severity=Severity.MAJOR,
            state=state,
            dedup_key="interface.down:sw1:Gi1/0/1",
            summary="Gi1/0/1 is down",
            cleared_at=T0 if state is AlarmState.CLEARED else None,
        )

    session.add_all([alarm(AlarmState.CLEARED), alarm(AlarmState.CLEARED), alarm()])
    await session.flush()
    await expect_integrity_error(session, alarm())
