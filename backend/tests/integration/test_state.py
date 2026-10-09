"""netops.db.state: "state of device D at time T for kind K" against a real database."""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from netops.db.enums import (
    CollectionKind,
    CollectionStatus,
    CollectionTrigger,
    DiscoverySource,
    MacEntryType,
)
from netops.db.models import CollectionRun, Device, MacEntry, VlanObservation
from netops.db.state import observations_of, run_at, runs_at, state_at

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

T0 = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


def minutes(n: int) -> datetime:
    return T0 + timedelta(minutes=n)


async def add_device(session: AsyncSession, hostname: str) -> Device:
    device = Device(hostname=hostname, discovered_via=DiscoverySource.SEED)
    session.add(device)
    await session.flush()
    return device


async def add_run(
    session: AsyncSession,
    device: Device,
    started_at: datetime,
    status: CollectionStatus = CollectionStatus.SUCCESS,
    kind: CollectionKind = CollectionKind.MAC_TABLE,
    macs: Iterable[str] = (),
) -> CollectionRun:
    """A run of ``kind`` with one MAC table row per MAC (rows share the run's start time)."""
    finished = status is not CollectionStatus.RUNNING
    run = CollectionRun(
        device_id=device.id,
        kind=kind,
        trigger=CollectionTrigger.SCHEDULED,
        status=status,
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=20) if finished else None,
        error="ssh timeout" if status is CollectionStatus.FAILED else None,
    )
    session.add(run)
    await session.flush()
    session.add_all(
        MacEntry(
            collected_at=run.started_at,
            run_id=run.id,
            device_id=device.id,
            vlan_id=20,
            mac=mac,
            entry_type=MacEntryType.DYNAMIC,
        )
        for mac in macs
    )
    await session.flush()
    return run


@pytest.fixture
async def history(session: AsyncSession) -> dict[str, CollectionRun | Device]:
    """sw1's MAC table runs between 10:00 and 10:50, plus noise that must not interfere."""
    sw1 = await add_device(session, "sw1")
    sw2 = await add_device(session, "sw2")
    await add_device(session, "sw3-never-polled")
    return {
        "sw1": sw1,
        "sw2": sw2,
        "ok_1000": await add_run(session, sw1, minutes(0), macs=["aa:aa:aa:00:00:01"]),
        "failed_1015": await add_run(session, sw1, minutes(15), CollectionStatus.FAILED),
        "ok_1030": await add_run(session, sw1, minutes(30), macs=["bb:bb:bb:00:00:02"]),
        "partial_1040": await add_run(
            session, sw1, minutes(40), CollectionStatus.PARTIAL, macs=["cc:cc:cc:00:00:03"]
        ),
        "running_1050": await add_run(session, sw1, minutes(50), CollectionStatus.RUNNING),
        # Other kind and other device at times that would win if they were not filtered out.
        "arp_1035": await add_run(session, sw1, minutes(35), kind=CollectionKind.ARP_TABLE),
        "sw2_1020": await add_run(session, sw2, minutes(20), macs=["dd:dd:dd:00:00:04"]),
    }


@pytest.mark.parametrize(
    ("at", "expected"),
    [
        (minutes(-1), None),  # before the first run: no state
        (minutes(0), "ok_1000"),  # started_at <= T is inclusive
        (minutes(20), "ok_1000"),  # the failed 10:15 run is ignored
        (minutes(30), "ok_1030"),
        (minutes(45), "ok_1030"),  # partial runs are ignored by default
        (minutes(60), "ok_1030"),  # still-running runs are ignored
        (None, "ok_1030"),  # None means now
    ],
)
async def test_run_at(
    session: AsyncSession,
    history: dict[str, CollectionRun | Device],
    at: datetime | None,
    expected: str | None,
) -> None:
    run = await run_at(session, history["sw1"].id, CollectionKind.MAC_TABLE, at)
    assert run is (history[expected] if expected else None)


async def test_run_at_can_include_partial_runs(
    session: AsyncSession, history: dict[str, CollectionRun | Device]
) -> None:
    run = await run_at(
        session, history["sw1"].id, CollectionKind.MAC_TABLE, minutes(45), include_partial=True
    )
    assert run is history["partial_1040"]


async def test_run_at_respects_kind(
    session: AsyncSession, history: dict[str, CollectionRun | Device]
) -> None:
    run = await run_at(session, history["sw1"].id, CollectionKind.ARP_TABLE, minutes(40))
    assert run is history["arp_1035"]
    assert await run_at(session, history["sw1"].id, CollectionKind.STP) is None


async def test_run_at_rejects_naive_datetimes(
    session: AsyncSession, history: dict[str, CollectionRun | Device]
) -> None:
    naive = datetime(2026, 10, 1)  # noqa: DTZ001 - the point of the test
    with pytest.raises(ValueError, match="timezone-aware"):
        await run_at(session, history["sw1"].id, CollectionKind.MAC_TABLE, naive)


async def test_state_at_returns_the_rows_of_the_run(
    session: AsyncSession, history: dict[str, CollectionRun | Device]
) -> None:
    sw1 = history["sw1"].id
    before = await state_at(session, MacEntry, sw1, minutes(20))
    after = await state_at(session, MacEntry, sw1, minutes(35))
    assert [row.mac for row in before] == ["aa:aa:aa:00:00:01"]
    assert [row.mac for row in after] == ["bb:bb:bb:00:00:02"]
    assert await state_at(session, MacEntry, sw1, minutes(-1)) == []


async def test_runs_at_returns_one_run_per_device(
    session: AsyncSession, history: dict[str, CollectionRun | Device]
) -> None:
    runs = await runs_at(session, CollectionKind.MAC_TABLE, minutes(25))
    assert runs == {history["sw1"].id: history["ok_1000"], history["sw2"].id: history["sw2_1020"]}

    only_sw2 = await runs_at(session, CollectionKind.MAC_TABLE, device_ids=[history["sw2"].id])
    assert only_sw2 == {history["sw2"].id: history["sw2_1020"]}


async def test_observations_of_rejects_a_table_of_another_kind(
    history: dict[str, CollectionRun | Device],
) -> None:
    run = history["ok_1000"]
    assert isinstance(run, CollectionRun)
    with pytest.raises(ValueError, match="vlans"):
        observations_of(VlanObservation, run)
