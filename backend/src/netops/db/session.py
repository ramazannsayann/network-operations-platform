"""Async SQLAlchemy engine and session factory (asyncpg driver)."""

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from netops.core.settings import get_settings


def create_engine(url: URL | str, **kwargs: Any) -> AsyncEngine:
    """Create an engine; use this instead of create_async_engine.

    inet/cidr values come back as canonical strings, as the models declare them (asyncpg
    would otherwise return ipaddress objects). PostgreSQL prints a /32 inet without its mask.
    """
    return create_async_engine(url, native_inet_types=False, **kwargs)


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide engine. No connection is made until it is first used."""
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session that is closed after the request."""
    async with get_sessionmaker()() as session:
        yield session


async def ping_database() -> None:
    """Run ``SELECT 1``; raises if the database is unreachable."""
    async with get_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


async def dispose_engine() -> None:
    """Close all pooled connections, if the engine was ever created."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()
