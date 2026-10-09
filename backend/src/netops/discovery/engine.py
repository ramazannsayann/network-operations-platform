"""Breadth-first CDP/LLDP discovery (M1, proposal 7.1).

One discovery run from start to finish (the Celery task ``netops.discover`` calls
``run_discovery``):

1. Level 0 holds the seeds. Every level is processed in parallel, with at most as many SSH
   sessions as the run holds slots (<= SSH_MAX_CONCURRENCY, see netops.inventory.locks).
2. Phase A, per address: log in with the credential profiles in order, at most two attempts
   per device, the profile that worked last time first. A rejected profile is never retried,
   so a wrong password costs at most two failed logins on the AAA server. The session runs
   the facts and neighbours commands plus ``show ip route`` (which tells L3 switches from
   L2 ones, and which L3 devices need anyway).
3. Identification, one address at a time: the chassis serials decide which device this is.
   A serial already reached in this run makes the address a ``duplicate`` (a second
   management address of the same device, e.g. another SVI); otherwise the device is
   updated or created and its facts and neighbours runs are stored (the M2 collectors).
   In-scope neighbours of supported platforms are queued for the next level; the others are
   recorded and created as unmanaged placeholders, so the map shows them, but never
   connected to.
4. Phase B: the remaining collectors for the device's type, over a second session.
5. After the last level, links are rebuilt from the neighbour observations (links no longer
   seen become inactive) and device roles are derived again.

Scope checks, de-duplication and everything stored use management addresses; the
connection-target resolver (netops.netaccess.target) only decides which socket a session
opens.
"""

import asyncio
import ipaddress
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from netops.core.secrets import redact
from netops.core.settings import Settings
from netops.db.enums import (
    CollectionKind,
    CollectionTrigger,
    CredentialKind,
    DeviceType,
    DiscoveryItemStatus,
    DiscoverySource,
    JobStatus,
    ManagementStatus,
    NeighborProtocol,
    OsFamily,
    Reachability,
)
from netops.db.models import (
    CredentialProfile,
    Device,
    DeviceSerial,
    DiscoveryRun,
    DiscoveryRunItem,
    Interface,
    InterfaceAddress,
)
from netops.db.session import create_engine
from netops.discovery import classify
from netops.discovery.links import rebuild_links
from netops.discovery.roles import assign_roles
from netops.inventory.collectors import COLLECTORS, commands_for, kinds_for
from netops.inventory.locks import take_free_ssh_slots, try_lock_device, unlock_device
from netops.inventory.persistence import complete_run, fail_run, start_run
from netops.netaccess import DeviceAccess, ShowResult, TargetResolver, device_access, run_show
from netops.netaccess.inventory import NETMIKO_PLATFORMS
from netops.parsing import CommandError, ParseError, parse
from netops.parsing.models import Facts, Neighbor
from netops.workers.jobs import job_finished, job_progress, job_started

logger = logging.getLogger(__name__)

# Login attempts per device and run (proposal 7.1: protects accounts on the AAA server).
MAX_ATTEMPTS = 2
ROUTES_COMMAND = "show ip route"
PHASE_A_KINDS = (CollectionKind.FACTS, CollectionKind.NEIGHBORS)
PHASE_A_COMMANDS = (
    *COLLECTORS[CollectionKind.FACTS].commands,
    *COLLECTORS[CollectionKind.NEIGHBORS].commands,
    ROUTES_COMMAND,
)
_SOURCES = {NeighborProtocol.CDP: DiscoverySource.CDP, NeighborProtocol.LLDP: DiscoverySource.LLDP}
_SKIPPED = frozenset(
    {
        DiscoveryItemStatus.OUT_OF_SCOPE,
        DiscoveryItemStatus.UNSUPPORTED_PLATFORM,
        DiscoveryItemStatus.NO_MGMT_IP,
    }
)
_ERRORS = frozenset({DiscoveryItemStatus.AUTH_FAILED, DiscoveryItemStatus.UNREACHABLE})
_PLACEHOLDER_STATUS = {
    DiscoveryItemStatus.OUT_OF_SCOPE: ManagementStatus.OUT_OF_SCOPE,
    DiscoveryItemStatus.UNSUPPORTED_PLATFORM: ManagementStatus.UNSUPPORTED_PLATFORM,
    DiscoveryItemStatus.NO_MGMT_IP: ManagementStatus.OUT_OF_SCOPE,
    DiscoveryItemStatus.AUTH_FAILED: ManagementStatus.AUTH_FAILED,
    DiscoveryItemStatus.UNREACHABLE: ManagementStatus.UNREACHABLE,
}


class NoSshSlotError(Exception):
    """Every SSH session slot is in use; the run should be retried later."""


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Target:
    """An address to deal with, and how the run got there."""

    address: str
    hop: int
    source: DiscoverySource
    via_device_id: uuid.UUID | None = None
    via_interface: str | None = None
    neighbor: Neighbor | None = None


@dataclass
class Login:
    """Phase A for one target: the last attempt's result and the profile it used."""

    target: Target
    started_at: datetime
    attempts: int = 0
    profile: CredentialProfile | None = None
    result: ShowResult | None = None


@dataclass
class Counters:
    queued: int = 0
    scanned: int = 0
    found: int = 0
    new_devices: int = 0
    skipped: int = 0
    errors: int = 0

    def apply(self, run: DiscoveryRun) -> None:
        run.queued, run.scanned, run.found = self.queued, self.scanned, self.found
        run.new_devices, run.skipped, run.errors = self.new_devices, self.skipped, self.errors


async def run_discovery(
    run_id: uuid.UUID, settings: Settings, resolve: TargetResolver | None = None
) -> JobStatus:
    """Execute one requested discovery run; returns its final status.

    Raises NoSshSlotError (before touching the run) when no SSH session slot is free.
    """
    engine = create_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            locks = await connection.execution_options(isolation_level="AUTOCOMMIT")
            slots = await take_free_ssh_slots(locks, settings.ssh_max_concurrency)
            if slots == 0:
                raise NoSshSlotError
            run_settings = settings.model_copy(update={"ssh_max_concurrency": slots})
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            return await Discovery(sessions, locks, run_id, run_settings, resolve).run()
            # Closing the lock connection releases the slots and any device locks.
    finally:
        await engine.dispose()


class Discovery:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        locks: AsyncConnection,
        run_id: uuid.UUID,
        settings: Settings,
        resolve: TargetResolver | None,
    ) -> None:
        self.sessions = sessions
        self.locks = locks
        self.run_id = run_id
        self.settings = settings
        self.resolve = resolve
        self.counters = Counters()
        self.profiles: list[CredentialProfile] = []
        self.allowed: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        # Addresses queued or dealt with in this run, and address-less neighbours recorded.
        self.seen: set[str] = set()
        self.seen_names: set[str] = set()
        # Devices reached in this run -> the address they were reached at.
        self.reached: dict[uuid.UUID, str] = {}
        self.job_id: uuid.UUID | None = None

    # --- the run --------------------------------------------------------------------------

    async def run(self) -> JobStatus:
        async with self.sessions() as session:
            run = await session.get(DiscoveryRun, self.run_id)
            if run is None:
                raise LookupError(f"discovery run {self.run_id} does not exist")
            self.job_id = run.job_id
            # A redelivered task starts the run over.
            await session.execute(
                delete(DiscoveryRunItem).where(DiscoveryRunItem.run_id == self.run_id)
            )
            run.status, run.started_at, run.finished_at, run.error = (
                JobStatus.RUNNING,
                utcnow(),
                None,
                None,
            )
            self.counters.apply(run)
            await session.commit()
            await job_started(session, run.job_id)
            seeds = [str(ipaddress.ip_address(seed)) for seed in run.seeds]

            error = None
            try:
                await self._prepare(session, run)
                level = [Target(seed, 0, DiscoverySource.SEED) for seed in _sorted(seeds)]
                self.seen.update(seeds)
                while level:
                    level = await self._level(session, level)
                await rebuild_links(session)
                await assign_roles(session)
            except Exception as exc:
                logger.exception("discovery run failed", extra={"run_id": str(self.run_id)})
                await session.rollback()
                error = redact(f"{type(exc).__name__}: {exc}", self._secrets())

            run = await session.get(DiscoveryRun, self.run_id, populate_existing=True)
            if run is None:
                raise LookupError(f"discovery run {self.run_id} disappeared")
            run.status = JobStatus.FAILED if error else JobStatus.SUCCEEDED
            run.error = error
            run.finished_at = utcnow()
            self.counters.queued = 0
            self.counters.apply(run)
            status = run.status
            await session.commit()
            handled = self._handled()
            await job_progress(session, run.job_id, handled, handled, self._summary())
            await job_finished(session, run.job_id, error)
            logger.info(
                "discovery run finished",
                extra={"run_id": str(self.run_id), "status": status.value, **vars(self.counters)},
            )
            return status

    def _secrets(self) -> tuple[Any, ...]:
        return tuple(s for p in self.profiles for s in (p.password, p.enable_secret) if s)

    async def _prepare(self, session: AsyncSession, run: DiscoveryRun) -> None:
        self.allowed = [
            ipaddress.ip_network(subnet, strict=False) for subnet in run.allowed_subnets
        ]
        for profile_id in run.credential_profile_ids:
            profile = await session.get(CredentialProfile, profile_id)
            if profile is None or profile.kind is not CredentialKind.SSH:
                raise ValueError(f"credential profile {profile_id} is not an SSH profile")
            self.profiles.append(profile)

    def _in_scope(self, address: str) -> bool:
        ip = ipaddress.ip_address(address)
        return any(ip.version == net.version and ip in net for net in self.allowed)

    def _handled(self) -> int:
        c = self.counters
        return c.found + c.skipped + c.errors

    def _summary(self) -> str:
        c = self.counters
        return (
            f"{c.found} devices found ({c.new_devices} new), {c.skipped} skipped, "
            f"{c.errors} errors, {c.queued} queued"
        )

    async def _progress(self, session: AsyncSession, hop: int) -> None:
        run = await session.get(DiscoveryRun, self.run_id)
        if run is not None:
            self.counters.apply(run)
            await session.commit()
        if self.job_id is not None:
            await job_progress(
                session, self.job_id, self._handled(), None, f"hop {hop}: {self._summary()}"
            )

    async def _level(self, session: AsyncSession, level: Sequence[Target]) -> list[Target]:
        """Deal with one BFS level; returns the next one."""
        hop = level[0].hop
        in_scope = []
        for target in level:
            if self._in_scope(target.address):
                in_scope.append(target)
            else:
                await self._skip(session, target, DiscoveryItemStatus.OUT_OF_SCOPE)
        self.counters.queued = len(in_scope)
        logins = await self._login(session, in_scope)

        next_level: list[Target] = []
        to_collect: list[tuple[Device, CredentialProfile]] = []
        for login in sorted(logins, key=lambda item: _address_key(item.target.address)):
            result, profile = login.result, login.profile
            if result is None or result.error or profile is None:
                await self._login_failed(session, login)
                continue
            identified = await self._identify(session, login, result, profile)
            if identified is None:
                continue
            device, locked = identified
            if locked:
                to_collect.append((device, profile))
            next_level.extend(await self._neighbors(session, device, login.target, result))

        try:
            await self._collect_rest(session, to_collect)
        finally:
            for device, _ in to_collect:
                await unlock_device(self.locks, device.id)
        self.counters.queued = len(next_level)
        await self._progress(session, hop)
        return next_level

    # --- phase A: log in, identify ----------------------------------------------------------

    async def _login(self, session: AsyncSession, targets: Sequence[Target]) -> list[Login]:
        known = await self._devices_by_address(session, [t.address for t in targets])
        candidates: dict[str, list[CredentialProfile]] = {}
        for target in targets:
            order: list[CredentialProfile] = []
            device = known.get(target.address)
            if device is not None and device.credential_profile_id is not None:
                remembered = await session.get(CredentialProfile, device.credential_profile_id)
                if remembered is not None and remembered.kind is CredentialKind.SSH:
                    order.append(remembered)
            order += [p for p in self.profiles if all(p.id != o.id for o in order)]
            candidates[target.address] = order[:MAX_ATTEMPTS]

        started_at = utcnow()
        logins = {t.address: Login(t, started_at) for t in targets}
        pending = list(targets)
        for attempt in range(MAX_ATTEMPTS):
            batch: dict[uuid.UUID, tuple[Target, CredentialProfile, DeviceAccess]] = {}
            for target in pending:
                if attempt >= len(candidates[target.address]):
                    continue
                profile = candidates[target.address][attempt]
                access = self._access(target, profile, known.get(target.address))
                if access is not None:
                    batch[access.device_id] = (target, profile, access)
            if not batch:
                break
            accesses = [access for _, _, access in batch.values()]
            results = await asyncio.to_thread(
                run_show, accesses, PHASE_A_COMMANDS, self.settings, self.resolve
            )
            pending = []
            for access_id, (target, profile, _) in batch.items():
                login = logins[target.address]
                login.attempts += 1
                login.profile, login.result = profile, results[access_id]
                if login.result.auth_failed:
                    pending.append(target)
        self.counters.scanned += len(targets)
        return list(logins.values())

    def _access(
        self, target: Target, profile: CredentialProfile, known: Device | None
    ) -> DeviceAccess | None:
        if profile.password is None:
            return None
        os_family = known.os_family if known is not None else OsFamily.UNKNOWN
        return DeviceAccess(
            device_id=uuid.uuid4(),  # identifies the session only; the device is not known yet
            name=classify.short_name(target.neighbor.remote_name if target.neighbor else None)
            or target.address,
            host=target.address,
            port=(known.ssh_port if known and known.ssh_port else self.settings.ssh_port),
            platform=NETMIKO_PLATFORMS.get(os_family, "cisco_ios"),
            username=profile.username,
            password=profile.password,
            enable_secret=profile.enable_secret,
        )

    async def _devices_by_address(
        self, session: AsyncSession, addresses: Sequence[str]
    ) -> dict[str, Device]:
        """Known devices owning these addresses: as management address, or on an interface
        (a second management SVI), so their remembered profile can be tried first."""
        if not addresses:
            return {}
        host = func.host(InterfaceAddress.address)
        found: dict[str, Device] = {}
        for device, address in await session.execute(
            select(Device, host)
            .join(Interface, Interface.device_id == Device.id)
            .join(InterfaceAddress, InterfaceAddress.interface_id == Interface.id)
            .where(host.in_(addresses))
        ):
            found[address] = device
        for device in await session.scalars(select(Device).where(Device.mgmt_ip.in_(addresses))):
            found[str(device.mgmt_ip)] = device
        return found

    async def _login_failed(self, session: AsyncSession, login: Login) -> None:
        result = login.result
        status = (
            DiscoveryItemStatus.AUTH_FAILED
            if result is None or result.auth_failed
            else DiscoveryItemStatus.UNREACHABLE
        )
        error = (result.error if result else None) or "no usable SSH credential profile"
        await self._skip(session, login.target, status, attempts=login.attempts, error=error)

    async def _identify(
        self, session: AsyncSession, login: Login, result: ShowResult, profile: CredentialProfile
    ) -> tuple[Device, bool] | None:
        """Find or create the device behind a successful login and store phase A's runs.

        Returns (device, locked), or None if the address is a duplicate or not a supported
        device. ``locked``: this run holds the device's collection lock (it is released at
        the end of the level); without it nothing is stored for the device.
        """
        target, outputs = login.target, result.outputs
        facts = _parse(outputs, "show version")
        if not isinstance(facts, Facts):
            await self._skip(
                session,
                target,
                DiscoveryItemStatus.UNSUPPORTED_PLATFORM,
                attempts=login.attempts,
                error="show version output not recognised as Cisco IOS / IOS-XE",
            )
            return None
        routes = _parse(outputs, ROUTES_COMMAND)
        device_type = classify.device_type(facts, routes if isinstance(routes, list) else None)

        device = await self._device_by_serial(session, facts.serials)
        if device is not None and device.id in self.reached:
            await self._item(
                session,
                target,
                DiscoveryItemStatus.DUPLICATE,
                device_id=device.id,
                attempts=login.attempts,
                error=f"same chassis as {self.reached[device.id]}",
            )
            return None
        if device is None:
            device = await session.scalar(select(Device).where(Device.mgmt_ip == target.address))
        if device is None and facts.hostname:
            # An address-less placeholder created from a neighbour report.
            device = await session.scalar(
                select(Device).where(
                    Device.mgmt_ip.is_(None),
                    func.lower(Device.hostname) == facts.hostname.lower(),
                    ~select(DeviceSerial.serial)
                    .where(DeviceSerial.device_id == Device.id)
                    .exists(),
                )
            )
        is_new = device is None
        now = utcnow()
        if device is None:
            # Not found by this address above, so the address is free.
            device = Device(
                id=uuid.uuid4(),
                hostname=facts.hostname,
                mgmt_ip=target.address,
                discovered_via=target.source,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(device)
        elif device.mgmt_ip is None and not await self._address_taken(session, target.address):
            device.mgmt_ip = target.address
        device.hostname = facts.hostname or device.hostname
        device.device_type = device_type
        device.is_managed = True
        device.management_status = ManagementStatus.MANAGED
        device.credential_profile_id = profile.id
        device.reachability = Reachability.REACHABLE
        device.last_seen_at = now
        await session.commit()
        self.reached[device.id] = target.address

        locked = await try_lock_device(self.locks, device.id)
        if locked:
            kinds = [*PHASE_A_KINDS]
            if CollectionKind.ROUTES in kinds_for(device_type):
                kinds.append(CollectionKind.ROUTES)
            for kind in kinds:
                run_id = await start_run(
                    session, device.id, kind, CollectionTrigger.DISCOVERY, login.started_at
                )
                await complete_run(session, device.id, run_id, outputs, result.command_errors)
        await self._item(
            session,
            target,
            DiscoveryItemStatus.DISCOVERED,
            device_id=device.id,
            is_new=is_new,
            attempts=login.attempts,
            error=None if locked else "collection in progress elsewhere; data not stored",
        )
        return device, locked

    async def _device_by_serial(
        self, session: AsyncSession, serials: Sequence[str]
    ) -> Device | None:
        if not serials:
            return None
        return await session.scalar(
            select(Device)
            .join(DeviceSerial, DeviceSerial.device_id == Device.id)
            .where(DeviceSerial.serial.in_(serials))
            .limit(1)
        )

    async def _address_taken(self, session: AsyncSession, address: str) -> bool:
        return (
            await session.scalar(select(Device.id).where(Device.mgmt_ip == address).limit(1))
        ) is not None

    async def _neighbors(
        self, session: AsyncSession, device: Device, origin: Target, result: ShowResult
    ) -> list[Target]:
        """Queue in-scope neighbours of supported platforms; record the others."""
        outputs = result.outputs
        neighbors: list[Neighbor] = []
        for command in COLLECTORS[CollectionKind.NEIGHBORS].commands:  # CDP before LLDP
            parsed = _parse(outputs, command)
            if isinstance(parsed, list):
                neighbors += sorted(parsed, key=lambda n: n.local_interface)

        targets = []
        hop = origin.hop + 1
        for neighbor in neighbors:
            address = neighbor.remote_mgmt_ip
            target = Target(
                address=address or "",
                hop=hop,
                source=_SOURCES[neighbor.protocol],
                via_device_id=device.id,
                via_interface=neighbor.local_interface,
                neighbor=neighbor,
            )
            if address is None:
                name = classify.short_name(neighbor.remote_name)
                if name and name.lower() not in self.seen_names:
                    self.seen_names.add(name.lower())
                    await self._skip(session, target, DiscoveryItemStatus.NO_MGMT_IP)
                continue
            if address in self.seen:
                continue
            self.seen.add(address)
            if not self._in_scope(address):
                await self._skip(session, target, DiscoveryItemStatus.OUT_OF_SCOPE)
            elif not classify.is_supported(neighbor):
                await self._skip(session, target, DiscoveryItemStatus.UNSUPPORTED_PLATFORM)
            else:
                targets.append(target)
        return sorted(targets, key=lambda t: _address_key(t.address))

    # --- phase B: everything else -------------------------------------------------------------

    async def _collect_rest(
        self, session: AsyncSession, devices: Sequence[tuple[Device, CredentialProfile]]
    ) -> None:
        by_type: dict[DeviceType, list[tuple[Device, CredentialProfile]]] = {}
        for device, profile in devices:
            by_type.setdefault(device.device_type, []).append((device, profile))
        for device_type, members in by_type.items():
            done = {*PHASE_A_KINDS, CollectionKind.ROUTES}
            kinds = [k for k in kinds_for(device_type) if k not in done]
            commands = list(dict.fromkeys(c for k in kinds for c in commands_for(k, device_type)))
            if not kinds:
                continue
            runs = {
                device.id: {
                    kind: await start_run(session, device.id, kind, CollectionTrigger.DISCOVERY)
                    for kind in kinds
                }
                for device, _ in members
            }
            accesses = [device_access(d, p, self.settings.ssh_port) for d, p in members]
            results = await asyncio.to_thread(
                run_show, accesses, commands, self.settings, self.resolve
            )
            for device, _ in members:
                result = results[device.id]
                for run_id in runs[device.id].values():
                    if result.error:
                        await fail_run(session, run_id, result.error)
                    else:
                        await complete_run(
                            session, device.id, run_id, result.outputs, result.command_errors
                        )

    # --- recording ------------------------------------------------------------------------

    async def _skip(
        self,
        session: AsyncSession,
        target: Target,
        status: DiscoveryItemStatus,
        *,
        attempts: int = 0,
        error: str | None = None,
    ) -> None:
        """Record an address (or neighbour) the run did not manage, with a placeholder."""
        device, is_new = await self._placeholder(session, target, status)
        await self._item(
            session,
            target,
            status,
            device_id=device.id,
            is_new=is_new,
            attempts=attempts,
            error=error,
        )

    async def _placeholder(
        self, session: AsyncSession, target: Target, status: DiscoveryItemStatus
    ) -> tuple[Device, bool]:
        neighbor = target.neighbor
        name = classify.short_name(neighbor.remote_name if neighbor else None)
        platform = neighbor.remote_platform if neighbor else None
        device = None
        if target.address:
            device = await session.scalar(select(Device).where(Device.mgmt_ip == target.address))
        elif name:
            device = await session.scalar(
                select(Device).where(func.lower(Device.hostname) == name.lower()).limit(1)
            )
        is_new = device is None
        now = utcnow()
        if device is None:
            device = Device(
                id=uuid.uuid4(),
                hostname=name,
                mgmt_ip=target.address or None,
                device_type=DeviceType.UNKNOWN,
                discovered_via=target.source,
                is_managed=False,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(device)
        management = _PLACEHOLDER_STATUS[status]
        # A managed device merely not crawled (out of scope this time) keeps its status.
        if not (device.is_managed and status in _SKIPPED):
            device.management_status = management
        if status is DiscoveryItemStatus.UNREACHABLE:
            device.reachability = Reachability.UNREACHABLE
        device.hostname = device.hostname or name
        if neighbor is not None:
            if device.device_type is DeviceType.UNKNOWN:
                device.device_type = classify.neighbor_type(neighbor)
            device.model = device.model or classify.model_from_platform(platform)
            if device.vendor is None and platform and "cisco" in platform.lower():
                device.vendor = "Cisco"
        device.last_seen_at = now
        await session.commit()
        return device, is_new

    async def _item(
        self,
        session: AsyncSession,
        target: Target,
        status: DiscoveryItemStatus,
        *,
        device_id: uuid.UUID | None = None,
        is_new: bool = False,
        attempts: int = 0,
        error: str | None = None,
    ) -> None:
        neighbor = target.neighbor
        session.add(
            DiscoveryRunItem(
                run_id=self.run_id,
                address=target.address or None,
                hop=target.hop,
                via_device_id=target.via_device_id,
                via_interface=target.via_interface,
                source=target.source,
                neighbor_name=neighbor.remote_name if neighbor else None,
                platform=neighbor.remote_platform if neighbor else None,
                status=status,
                device_id=device_id,
                is_new=is_new,
                attempts=attempts,
                error=error,
                occurred_at=utcnow(),
            )
        )
        await session.commit()
        if status is DiscoveryItemStatus.DISCOVERED:
            self.counters.found += 1
            self.counters.new_devices += is_new
        elif status in _SKIPPED:
            self.counters.skipped += 1
        elif status in _ERRORS:
            self.counters.errors += 1


def _parse(outputs: dict[str, str], command: str) -> object | None:
    raw = outputs.get(command)
    if raw is None:
        return None
    try:
        return parse(command, raw)
    except (CommandError, ParseError):
        return None


def _address_key(address: str) -> tuple[int, int]:
    ip = ipaddress.ip_address(address)
    return (ip.version, int(ip))


def _sorted(addresses: Sequence[str]) -> list[str]:
    return sorted(dict.fromkeys(addresses), key=_address_key)
