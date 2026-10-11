"""Per-client-address rate limits for the login and MFA endpoints (fixed windows in Redis).

Redis is shared by all API processes. If it is unreachable the limiter lets requests
through and logs it: the per-account lockout (in the database) still stops password
guessing. Tests use ``MemoryRateLimiter``.
"""

import logging
import time
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from netops.core.redis import get_redis

logger = logging.getLogger(__name__)


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window_seconds: int) -> int | None:
        """Count one request; seconds until the window resets if it is over ``limit``."""
        ...


class RedisRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def hit(self, key: str, limit: int, window_seconds: int) -> int | None:
        name = f"netops:ratelimit:{key}"
        try:
            count = int(await self.redis.incr(name))
            if count == 1:
                await self.redis.expire(name, window_seconds)
            if count <= limit:
                return None
            ttl = int(await self.redis.ttl(name))
            return ttl if ttl > 0 else window_seconds
        except RedisError as exc:
            logger.warning("rate limiter unavailable", extra={"error": type(exc).__name__})
            return None


class MemoryRateLimiter:
    """One process only (tests)."""

    def __init__(self) -> None:
        self.windows: dict[str, tuple[float, int]] = {}

    async def hit(self, key: str, limit: int, window_seconds: int) -> int | None:
        now = time.monotonic()
        start, count = self.windows.get(key, (now, 0))
        if now - start >= window_seconds:
            start, count = now, 0
        self.windows[key] = (start, count + 1)
        if count + 1 <= limit:
            return None
        return max(1, int(window_seconds - (now - start)))


def get_rate_limiter() -> RateLimiter:
    return RedisRateLimiter(get_redis())
