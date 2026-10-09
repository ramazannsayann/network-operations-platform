"""FastAPI application entry point (``uvicorn netops.main:app``)."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from netops import __version__
from netops.api.app import build_api
from netops.core.logging import configure_logging
from netops.core.redis import close_redis
from netops.core.settings import get_settings
from netops.db.session import dispose_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("api started", extra={"version": __version__, "env": get_settings().app_env})
    yield
    await dispose_engine()
    await close_redis()
    logger.info("api stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    return build_api(lifespan=lifespan)


app = create_app()
