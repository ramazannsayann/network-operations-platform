"""Collectors end to end: fake SSH device (127.0.0.1) -> collect_device -> test database."""

import asyncio
import secrets
import uuid
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import URL, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from netops.core.secrets import Secret
from netops.core.settings import get_settings
from netops.db import models as m
from netops.db.enums import (
    CollectionKind,
    CollectionStatus,
    CollectionTrigger,
    CredentialKind,
    DiscoverySource,
    Duplex,
    MacEntryType,
    Reachability,
)
from netops.db.session import create_engine
from netops.db.state import state_at
from netops.inventory.cleanup import cleanup_collection_runs
from netops.inventory.collectors import DEFAULT_KINDS
from netops.inventory.locks import try_lock_device
from netops.inventory.persistence import ingest_raw
from netops.inventory.tasks import collect_device
from netops.netaccess import ReadOnlyCommandError, load_device_access, run_show
from netops_fakes.device import FakeCiscoDevice, load_outputs

pytestmark = pytest.mark.integration

LAB_DEVICE = Path(__file__).resolve().parents[3] / "lab" / "fixtures" / "devices" / "dist-sw1"
USERNAME = "netops-ro"
PASSWORD = "pw-" + secrets.token_hex(8)  # random per run: no password literal in the repo


def run[T](make: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run ``make(session)`` against the database the application settings point at."""

    async def main() -> T:
        engine = create_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await make(session)
        finally:
            await engine.dispose()

    return asyncio.run(main())


@pytest.fixture
def app_on_test_database(monkeypatch: pytest.MonkeyPatch, migrated_database: URL) -> Iterator[None]:
    """Point netops' own settings (used by the Celery task) at the test database."""
    for name, value in {
        "POSTGRES_HOST": migrated_database.host,
        "POSTGRES_PORT": migrated_database.port,
        "POSTGRES_USER": migrated_database.username,
        "POSTGRES_PASSWORD": migrated_database.password,
        "POSTGRES_DB": migrated_database.database,
        "SSH_RETRIES": 0,
        "SSH_CONNECT_TIMEOUT_SECONDS": 5,
    }.items():
        monkeypatch.setenv(name, str(value))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def start_fake(outputs: dict[str, str] | None = None, password: str = PASSWORD) -> FakeCiscoDevice:
    device = FakeCiscoDevice(
        "dist-sw1", USERNAME, password, outputs if outputs is not None else load_outputs(LAB_DEVICE)
    )
    device.start()
    return device


@pytest.fixture
def fake_device(
    monkeypatch: pytest.MonkeyPatch, app_on_test_database: None
) -> Iterator[FakeCiscoDevice]:
    device = start_fake()
    monkeypatch.setenv("SSH_PORT", str(device.port))
    get_settings.cache_clear()
    yield device
    device.stop()


@pytest.fixture
def device_id(app_on_test_database: None) -> Iterator[uuid.UUID]:
    """A managed device at 127.0.0.1 with an SSH credential profile; removed afterwards."""

    async def create(session: AsyncSession) -> uuid.UUID:
        profile = m.CredentialProfile(
            id=uuid.uuid4(),
            name=f"lab-ro-{uuid.uuid4().hex[:8]}",
            kind=CredentialKind.SSH,
            username=USERNAME,
            password=Secret(PASSWORD),
        )
        device = m.Device(
            id=uuid.uuid4(),
            mgmt_ip="127.0.0.1",
            discovered_via=DiscoverySource.MANUAL,
            is_managed=True,
            credential_profile_id=profile.id,
        )
        session.add_all([profile, device])
        await session.commit()
        return device.id

    created = run(create)
    yield created

    async def remove(session: AsyncSession) -> None:
        device = await session.get(m.Device, created)
        assert device is not None
        profile_id = device.credential_profile_id
        await session.delete(device)
        await session.flush()
        await session.delete(await session.get(m.CredentialProfile, profile_id))
        await session.commit()

    run(remove)


def count(model: type[Any], device: uuid.UUID) -> int:
    async def query(session: AsyncSession) -> int:
        return (
            await session.scalar(
                select(func.count()).select_from(model).where(model.device_id == device)
            )
            or 0
        )

    return run(query)


def runs_by_kind(device: uuid.UUID) -> dict[CollectionKind, list[m.CollectionRun]]:
    async def query(session: AsyncSession) -> dict[CollectionKind, list[m.CollectionRun]]:
        rows = await session.scalars(
            select(m.CollectionRun).where(m.CollectionRun.device_id == device)
        )
        grouped: dict[CollectionKind, list[m.CollectionRun]] = {}
        for row in rows:
            grouped.setdefault(row.kind, []).append(row)
        return grouped

    return run(query)


def test_collect_device_stores_runs_entities_and_observations(
    fake_device: FakeCiscoDevice, device_id: uuid.UUID
) -> None:
    summary = collect_device.apply(args=[str(device_id)]).get()

    assert summary == {kind.value: "success" for kind in DEFAULT_KINDS}
    assert all(c.startswith(("show ", "terminal ")) or c == "exit" for c in fake_device.commands)

    async def entities(session: AsyncSession) -> dict[str, Any]:
        device = await session.get(m.Device, device_id)
        assert device is not None
        serials = await session.scalars(
            select(m.DeviceSerial).where(m.DeviceSerial.device_id == device_id)
        )
        interfaces = {
            i.name_normalized: i
            for i in await session.scalars(
                select(m.Interface).where(m.Interface.device_id == device_id)
            )
        }
        addresses = await session.execute(
            select(m.Interface.name_normalized, m.InterfaceAddress.address)
            .join(m.InterfaceAddress)
            .where(m.Interface.device_id == device_id)
        )
        hsrp = await session.execute(
            select(
                m.HsrpObservation.group_number,
                m.HsrpObservation.active_router,
                m.HsrpObservation.standby_router,
            )
            .where(m.HsrpObservation.device_id == device_id)
            .order_by(m.HsrpObservation.group_number)
        )
        macs = await state_at(session, m.MacEntry, device_id)
        return {
            "device": device,
            "serials": {s.serial: s.stack_member for s in serials},
            "interfaces": interfaces,
            "addresses": dict(addresses.all()),
            "hsrp": [tuple(row) for row in hsrp.all()],
            "macs": macs,
        }

    stored = run(entities)
    device = stored["device"]
    assert (device.hostname, device.model, device.os_family, device.os_version) == (
        "dist-sw1",
        "C9300-48P",
        "iosxe",
        "17.9.4a",
    )
    assert device.reachability is Reachability.REACHABLE
    assert device.last_polled_at is not None
    assert stored["serials"] == {"FOC0000X0A1": 1, "FOC0000X0B2": 2}

    interfaces = stored["interfaces"]
    assert len(interfaces) == 13
    port_channel = interfaces["Port-channel1"]
    assert interfaces["TenGigabitEthernet1/1/1"].parent_interface_id == port_channel.id
    assert interfaces["TenGigabitEthernet2/1/1"].parent_interface_id == port_channel.id
    assert interfaces["GigabitEthernet1/0/5"].late_collisions == 27
    assert interfaces["GigabitEthernet1/0/5"].duplex is Duplex.HALF
    assert interfaces["GigabitEthernet1/0/4"].err_disabled_reason == "unknown"
    assert interfaces["GigabitEthernet1/0/3"].allowed_vlans == [20, 30, 99]
    assert stored["addresses"] == {
        "Vlan20": "10.0.20.2/24",
        "Vlan30": "10.0.30.2/24",
        "Vlan99": "10.0.0.11/24",
        "Loopback0": "10.255.0.11",  # PostgreSQL prints a /32 inet without its mask
    }
    # "local" in show standby brief is resolved to the device's own address.
    assert stored["hsrp"] == [(20, "10.0.20.2", "10.0.20.3"), (30, "10.0.30.3", "10.0.30.2")]
    assert len(stored["macs"]) == 8
    assert {mac.entry_type for mac in stored["macs"]} == {MacEntryType.DYNAMIC}

    expected = {
        m.InterfaceSnapshot: 13,
        m.VlanObservation: 9,
        m.NeighborObservation: 4,
        m.MacEntry: 8,
        m.ArpEntry: 11,
        m.RouteEntry: 12,
        m.StpInstanceObservation: 3,
        m.StpPortObservation: 8,
        m.HsrpObservation: 2,
        m.OspfNeighborObservation: 2,
    }
    assert {model: count(model, device_id) for model in expected} == expected


def test_collecting_twice_adds_runs_but_not_entities(
    fake_device: FakeCiscoDevice, device_id: uuid.UUID
) -> None:
    collect_device.apply(args=[str(device_id)]).get()
    collect_device.apply(args=[str(device_id), ["interfaces", "facts"]]).get()

    runs = runs_by_kind(device_id)
    assert len(runs[CollectionKind.INTERFACES]) == 2
    assert len(runs[CollectionKind.MAC_TABLE]) == 1
    assert count(m.Interface, device_id) == 13
    assert count(m.DeviceSerial, device_id) == 2
    assert count(m.InterfaceSnapshot, device_id) == 26


def test_wrong_password_fails_every_run_without_leaking_it(
    monkeypatch: pytest.MonkeyPatch, device_id: uuid.UUID
) -> None:
    device = start_fake(password="pw-" + secrets.token_hex(8))  # not the profile's password
    monkeypatch.setenv("SSH_PORT", str(device.port))
    get_settings.cache_clear()
    try:
        summary = collect_device.apply(args=[str(device_id), ["facts", "interfaces"]]).get()
    finally:
        device.stop()

    assert summary == {"facts": "failed", "interfaces": "failed"}
    assert device.failed_logins == 1  # authentication failures are not retried
    for runs in runs_by_kind(device_id).values():
        (failed,) = runs
        assert failed.error == "SSH authentication failed (check the credential profile)"
        assert PASSWORD not in (failed.error or "")


def test_unreachable_device_marks_runs_failed(
    monkeypatch: pytest.MonkeyPatch, app_on_test_database: None, device_id: uuid.UUID
) -> None:
    closed = start_fake()
    closed.stop()  # nothing listens on this port any more
    monkeypatch.setenv("SSH_PORT", str(closed.port))
    get_settings.cache_clear()

    summary = collect_device.apply(args=[str(device_id), ["facts"]]).get()

    assert summary == {"facts": "failed"}
    (failed,) = runs_by_kind(device_id)[CollectionKind.FACTS]
    assert (failed.error or "").startswith("SSH connection failed")

    async def reachability(session: AsyncSession) -> Reachability:
        device = await session.get(m.Device, device_id)
        assert device is not None
        return device.reachability

    assert run(reachability) is Reachability.UNREACHABLE


def test_unsupported_command_makes_the_run_partial(
    monkeypatch: pytest.MonkeyPatch, device_id: uuid.UUID
) -> None:
    outputs = load_outputs(LAB_DEVICE)
    del outputs["show lldp neighbors detail"]  # the fake answers "% Invalid input detected"
    device = start_fake(outputs)
    monkeypatch.setenv("SSH_PORT", str(device.port))
    get_settings.cache_clear()
    try:
        summary = collect_device.apply(args=[str(device_id), ["neighbors", "vlans"]]).get()
    finally:
        device.stop()

    assert summary == {"neighbors": "partial", "vlans": "success"}
    (partial,) = runs_by_kind(device_id)[CollectionKind.NEIGHBORS]
    assert "show lldp neighbors detail" in (partial.error or "")
    assert "Invalid input detected" in (partial.error or "")
    assert count(m.NeighborObservation, device_id) == 3  # the CDP neighbours


def test_read_only_guard_blocks_before_anything_is_sent(
    fake_device: FakeCiscoDevice, device_id: uuid.UUID
) -> None:
    async def access(session: AsyncSession) -> Any:
        device = await session.get(m.Device, device_id)
        assert device is not None
        return await load_device_access(session, device, fake_device.port)

    device_access = run(access)
    with pytest.raises(ReadOnlyCommandError):
        run_show([device_access], ["show version", "configure terminal"])

    assert fake_device.sessions == 0
    assert fake_device.commands == []


def test_session_log_is_redacted(
    fake_device: FakeCiscoDevice, device_id: uuid.UUID, tmp_path: Path
) -> None:
    async def access(session: AsyncSession) -> Any:
        device = await session.get(m.Device, device_id)
        assert device is not None
        return await load_device_access(session, device, fake_device.port)

    settings = get_settings().model_copy(update={"ssh_session_log_dir": tmp_path})
    results = run_show([run(access)], ["show version"], settings)

    assert results[device_id].error is None
    log = (tmp_path / f"{device_id}.log").read_text()
    assert "show version" in log
    assert PASSWORD not in log


def test_a_device_is_not_collected_twice_at_the_same_time(
    fake_device: FakeCiscoDevice, device_id: uuid.UUID
) -> None:
    async def hold_lock_and_collect() -> dict[str, str]:
        engine = create_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                locks = await connection.execution_options(isolation_level="AUTOCOMMIT")
                assert await try_lock_device(locks, device_id)
                return await asyncio.to_thread(
                    lambda: collect_device.apply(args=[str(device_id)]).get()
                )
        finally:
            await engine.dispose()

    assert asyncio.run(hold_lock_and_collect()) == {"skipped": "device_locked"}
    assert fake_device.sessions == 0


# --- without SSH: replaying fixtures and housekeeping (rolled back after each test) ----------


@pytest.fixture
async def lab_device(session: AsyncSession) -> m.Device:
    device = m.Device(id=uuid.uuid4(), hostname="dist-sw1", discovered_via=DiscoverySource.MANUAL)
    session.add(device)
    await session.flush()
    return device


@pytest.mark.anyio
async def test_ingest_raw_replays_recorded_output(
    session: AsyncSession, lab_device: m.Device
) -> None:
    outputs = load_outputs(LAB_DEVICE)
    run_row = await ingest_raw(
        session,
        lab_device,
        CollectionKind.ARP_TABLE,
        {"show ip arp": outputs["show ip arp"]},
        trigger=CollectionTrigger.MANUAL,
    )
    assert run_row.status is CollectionStatus.SUCCESS
    arp = await state_at(session, m.ArpEntry, lab_device.id)
    assert len(arp) == 11
    assert {a.collected_at for a in arp} == {run_row.started_at}

    failed = await ingest_raw(session, lab_device, CollectionKind.ARP_TABLE, {})
    assert failed.status is CollectionStatus.FAILED
    assert failed.error == "show ip arp: no output"


@pytest.mark.anyio
async def test_cleanup_deletes_expired_runs_and_fails_abandoned_ones(
    session: AsyncSession, lab_device: m.Device
) -> None:
    now = datetime.now(UTC)

    def add_run(started: datetime, status: CollectionStatus) -> m.CollectionRun:
        row = m.CollectionRun(
            id=uuid.uuid4(),
            device_id=lab_device.id,
            kind=CollectionKind.MAC_TABLE,
            trigger=CollectionTrigger.SCHEDULED,
            status=status,
            started_at=started,
            finished_at=None if status is CollectionStatus.RUNNING else started,
        )
        session.add(row)
        return row

    expired = add_run(now - timedelta(days=40), CollectionStatus.SUCCESS)
    still_referenced = add_run(now - timedelta(days=41), CollectionStatus.SUCCESS)
    recent = add_run(now - timedelta(days=1), CollectionStatus.SUCCESS)
    abandoned = add_run(now - timedelta(hours=3), CollectionStatus.RUNNING)
    await session.flush()
    session.add(
        m.MacEntry(
            collected_at=still_referenced.started_at,
            run_id=still_referenced.id,
            device_id=lab_device.id,
            vlan_id=20,
            mac="3c:52:82:6e:41:9a",
            entry_type=MacEntryType.DYNAMIC,
        )
    )
    await session.flush()

    result = await cleanup_collection_runs(session, now)

    assert result == {"deleted": 1, "abandoned": 1}
    remaining = set(
        await session.scalars(
            select(m.CollectionRun.id).where(m.CollectionRun.device_id == lab_device.id)
        )
    )
    assert remaining == {still_referenced.id, recent.id, abandoned.id}
    assert expired.id not in remaining
    status = await session.scalar(
        text("SELECT status FROM collection_runs WHERE id = :id"), {"id": abandoned.id}
    )
    assert status == "failed"
