"""Shared asyncio Redis client used by the API (cache, pub/sub, health checks)."""

from functools import lru_cache

from redis.asyncio import Redis

from netops.core.settings import get_settings


@lru_cache
def get_redis() -> Redis:
    """Return the process-wide Redis client. Connections are opened lazily on first command."""
    settings = get_settings()
    client: Redis = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.health_check_timeout_seconds,
        socket_timeout=settings.health_check_timeout_seconds,
        health_check_interval=30,
    )
    return client


async def ping_redis() -> None:
    """Round-trip a PING to Redis; raises if it is unreachable."""
    await get_redis().ping()


async def close_redis() -> None:
    """Close the client's connection pool, if one was ever created."""
    if get_redis.cache_info().currsize:
        await get_redis().aclose()
        get_redis.cache_clear()
