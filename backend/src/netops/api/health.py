"""GET /api/health: reports whether the API can reach its database and Redis."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict

from netops import __version__
from netops.core.redis import ping_redis
from netops.core.settings import get_settings
from netops.db.session import ping_database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class ComponentStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class HealthResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"status": "ok", "version": "0.1.0", "db": "ok", "redis": "ok"},
                {"status": "degraded", "version": "0.1.0", "db": "ok", "redis": "error"},
            ]
        }
    )

    status: Literal["ok", "degraded"]
    version: str
    db: ComponentStatus
    redis: ComponentStatus


async def _probe(component: str, ping: Callable[[], Awaitable[None]]) -> ComponentStatus:
    try:
        async with asyncio.timeout(get_settings().health_check_timeout_seconds):
            await ping()
    except Exception:  # any failure at all means the component is unhealthy
        logger.warning("health check failed", extra={"component": component}, exc_info=True)
        return ComponentStatus.ERROR
    return ComponentStatus.OK


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def health(response: Response) -> HealthResponse:
    """Probe the database and Redis concurrently. Responds 503 if either is unreachable."""
    db, redis = await asyncio.gather(_probe("db", ping_database), _probe("redis", ping_redis))
    healthy = db is ComponentStatus.OK and redis is ComponentStatus.OK
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if healthy else "degraded", version=__version__, db=db, redis=redis
    )
