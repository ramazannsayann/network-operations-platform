"""Top-level API router, mounted under /api: unversioned health plus the versioned API."""

from fastapi import APIRouter

from netops.api import health, v1

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(v1.router)
