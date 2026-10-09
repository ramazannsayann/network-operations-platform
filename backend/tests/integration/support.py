"""Helpers for integration tests that work through netops' own settings (committed data)."""

import asyncio
import secrets
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from netops.core.secrets import Secret
from netops.core.settings import get_settings
from netops.db import models as m
from netops.db.enums import CredentialKind
from netops.db.session import create_engine

FAKELAB_TOPOLOGY = Path(__file__).resolve().parents[3] / "lab" / "fakelab" / "topology.yaml"
USERNAME = "netops-ro"
PASSWORD = "pw-" + secrets.token_hex(8)  # random per run: no password literal in the repo
OUTDATED = "pw-" + secrets.token_hex(8)  # a profile tried first that no device accepts
FAKELAB_REQUEST = {"seeds": ["10.255.0.2"], "allowed_subnets": ["10.255.0.0/24"]}


class Recorder:
    """Stands in for the Celery task queue (netops.api.v1.common.get_task_queue)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __call__(self, task: str, *args: Any) -> None:
        self.calls.append((task, args))


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


async def clear_inventory(session: AsyncSession) -> None:
    """Delete every device (cascading to interfaces, links and collection runs), discovery
    run, job and credential profile, for tests that need an empty inventory."""
    for model in (m.DiscoveryRun, m.Job, m.Device, m.CredentialProfile):
        await session.execute(delete(model))
    await session.commit()


async def create_lab_profiles(session: AsyncSession) -> list[uuid.UUID]:
    """An empty inventory and two SSH profiles: an outdated one first, then the lab's."""
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
