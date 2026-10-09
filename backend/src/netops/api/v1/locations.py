"""Locations (M2)."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Response, status
from sqlalchemy import func, select

from netops.api.problems import not_implemented, problems
from netops.api.schemas.locations import Location, LocationCreate, LocationPage, LocationUpdate
from netops.api.security import AUTHENTICATED
from netops.api.v1.common import DEFAULT_LIMIT, Limit, Offset, SearchText, Session
from netops.db import models as m

router = APIRouter(
    prefix="/locations",
    tags=["locations"],
    dependencies=AUTHENTICATED,
    responses=problems(401, 422, 501),
)

LocationSort = Literal["name", "-name", "path", "-path"]


@router.get("")
async def list_locations(
    session: Session,
    parent_id: UUID | None = None,
    q: SearchText = None,
    sort: LocationSort = "path",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> LocationPage:
    """Locations, optionally only the children of ``parent_id``; ``q`` searches names."""
    locations = {loc.id: loc for loc in await session.scalars(select(m.Location))}
    counts: dict[UUID, int] = dict(
        (
            await session.execute(
                select(m.Device.location_id, func.count())
                .where(m.Device.location_id.is_not(None))
                .group_by(m.Device.location_id)
            )
        ).all()  # type: ignore[arg-type]
    )

    def path(location: m.Location) -> str:
        names, seen = [], set()
        current: m.Location | None = location
        while current is not None and current.id not in seen:
            seen.add(current.id)
            names.append(current.name)
            current = locations.get(current.parent_id) if current.parent_id else None
        return " / ".join(reversed(names))

    items = [
        Location(
            id=loc.id,
            name=loc.name,
            building=loc.building,
            floor=loc.floor,
            description=loc.description,
            parent_id=loc.parent_id,
            path=path(loc),
            device_count=counts.get(loc.id, 0),
        )
        for loc in locations.values()
        if (parent_id is None or loc.parent_id == parent_id)
        and (q is None or q.lower() in loc.name.lower())
    ]
    key = sort.lstrip("-")
    items.sort(key=lambda item: getattr(item, key).lower(), reverse=sort.startswith("-"))
    return LocationPage(
        items=items[offset : offset + limit], total=len(items), limit=limit, offset=offset
    )


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
