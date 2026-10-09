"""Concurrency limits for device collection, as PostgreSQL advisory locks.

Session-level advisory locks live as long as the database connection that took them, so a
crashed worker can never leave a lock behind, and every worker process sees the same locks
without another service.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# First key of the two-key advisory lock form, per purpose.
_DEVICE_NAMESPACE = 0x4E4F_0001  # one collection per device at a time
_SSH_SLOT_NAMESPACE = 0x4E4F_0002  # at most SSH_MAX_CONCURRENCY sessions overall


async def try_lock_device(connection: AsyncConnection, device_id: uuid.UUID) -> bool:
    locked = await connection.scalar(
        text("SELECT pg_try_advisory_lock(:namespace, hashtext(:device_id))"),
        {"namespace": _DEVICE_NAMESPACE, "device_id": str(device_id)},
    )
    return bool(locked)


async def try_take_ssh_slot(connection: AsyncConnection, slots: int) -> int | None:
    """Take the first free slot of ``slots``; None when all are in use."""
    for slot in range(slots):
        locked = await connection.scalar(
            text("SELECT pg_try_advisory_lock(:namespace, :slot)"),
            {"namespace": _SSH_SLOT_NAMESPACE, "slot": slot},
        )
        if locked:
            return slot
    return None
