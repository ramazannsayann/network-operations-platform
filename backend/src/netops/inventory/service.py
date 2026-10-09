"""Collecting one device: SSH (read-only) -> parse -> store, one run per collection kind."""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from enum import StrEnum

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from netops.core.settings import Settings
from netops.db.enums import CollectionKind, CollectionStatus, CollectionTrigger, Reachability
from netops.db.models import Device
from netops.db.session import create_engine
from netops.inventory.collectors import commands_for, kinds_for
from netops.inventory.locks import try_lock_device, try_take_ssh_slot
from netops.inventory.persistence import complete_run, fail_run, start_run
from netops.netaccess import DeviceAccessError, load_device_access, run_show

logger = logging.getLogger(__name__)


class Busy(StrEnum):
    """Why a collection did not start."""

    DEVICE_LOCKED = "device_locked"  # another collection of this device is running
    NO_SSH_SLOT = "no_ssh_slot"  # SSH_MAX_CONCURRENCY sessions are already open


async def collect(
    sessions: async_sessionmaker,  # type: ignore[type-arg]
    device_id: uuid.UUID,
    kinds: Sequence[CollectionKind] | None,
    trigger: CollectionTrigger,
    settings: Settings,
) -> dict[CollectionKind, CollectionStatus]:
    """Run the collectors for ``kinds`` over one SSH session. Never raises for a device.

    ``kinds`` defaults to what the device's type supports (collectors.kinds_for); kinds the
    type does not have (VLANs on a router) are left out.
    """
    async with sessions() as session:
        device = await session.get(Device, device_id)
        if device is None:
            raise LookupError(f"device {device_id} does not exist")
        supported = kinds_for(device.device_type)
        kinds = [kind for kind in kinds or supported if kind in supported]
        runs = {kind: await start_run(session, device_id, kind, trigger) for kind in kinds}

        try:
            access = await load_device_access(session, device, settings.ssh_port)
        except DeviceAccessError as exc:
            return {
                kind: await fail_run(session, run_id, str(exc)) for kind, run_id in runs.items()
            }

        commands = [command for kind in kinds for command in commands_for(kind, device.device_type)]
        results = await asyncio.to_thread(run_show, [access], commands, settings)
        result = results[device_id]

        if result.error:
            if result.unreachable:
                device.reachability = Reachability.UNREACHABLE
                await session.commit()
            return {
                kind: await fail_run(session, run_id, result.error) for kind, run_id in runs.items()
            }

        statuses = {}
        for kind, run_id in runs.items():
            statuses[kind] = await complete_run(
                session, device_id, run_id, result.outputs, result.command_errors
            )
        logger.info(
            "device collected",
            extra={"device": access.name, "runs": {k.value: s.value for k, s in statuses.items()}},
        )
        return statuses


async def collect_device(
    device_id: uuid.UUID,
    kinds: Sequence[CollectionKind] | None,
    trigger: CollectionTrigger,
    settings: Settings,
) -> dict[CollectionKind, CollectionStatus] | Busy:
    """``collect`` behind the per-device lock and the global SSH session limit."""
    engine = create_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            locks = await connection.execution_options(isolation_level="AUTOCOMMIT")
            if not await try_lock_device(locks, device_id):
                return Busy.DEVICE_LOCKED
            if await try_take_ssh_slot(locks, settings.ssh_max_concurrency) is None:
                return Busy.NO_SSH_SLOT
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            return await collect(sessions, device_id, kinds, trigger, settings)
            # Closing the connection releases both locks.
    finally:
        await engine.dispose()
