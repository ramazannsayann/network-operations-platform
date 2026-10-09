"""Helpers for integration tests that work through netops' own settings (committed data)."""

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from netops.core.settings import get_settings
from netops.db import models as m
from netops.db.session import create_engine


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
