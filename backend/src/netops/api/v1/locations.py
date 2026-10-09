"""Locations (M2)."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Response, status

from netops.api.problems import not_implemented, problems
from netops.api.schemas.locations import Location, LocationCreate, LocationPage, LocationUpdate
from netops.api.security import AUTHENTICATED
from netops.api.v1.common import DEFAULT_LIMIT, Limit, Offset, SearchText

router = APIRouter(
    prefix="/locations",
    tags=["locations"],
    dependencies=AUTHENTICATED,
    responses=problems(401, 422, 501),
)

LocationSort = Literal["name", "-name", "path", "-path"]


@router.get("")
async def list_locations(
    parent_id: UUID | None = None,
    q: SearchText = None,
    sort: LocationSort = "path",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> LocationPage:
    """Locations, optionally only the children of ``parent_id``; ``q`` searches names."""
    raise not_implemented()


@router.post("", status_code=status.HTTP_201_CREATED, responses=problems(409))
async def create_location(body: LocationCreate) -> Location:
    """Create a location. 409 if the name already exists under the same parent."""
    raise not_implemented()


@router.get("/{location_id}", responses=problems(404))
async def get_location(location_id: UUID) -> Location:
    raise not_implemented()


@router.patch("/{location_id}", responses=problems(404, 409))
async def update_location(location_id: UUID, body: LocationUpdate) -> Location:
    """Partial update: only fields present in the body change."""
    raise not_implemented()


@router.delete(
    "/{location_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=problems(404, 409),
)
async def delete_location(location_id: UUID) -> None:
    """Delete a location. 409 while it still has child locations."""
    raise not_implemented()
