"""Top-level API router. Feature routers are included here and mounted under /api."""

from fastapi import APIRouter

from netops.api import health

api_router = APIRouter()
api_router.include_router(health.router)
