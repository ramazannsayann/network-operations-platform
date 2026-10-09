"""Locations (M2): campus > building > floor, maintained by users."""

from uuid import UUID

from pydantic import Field

from netops.api.schemas import examples as ex
from netops.api.schemas.common import ApiModel, Page, example

_FLOOR_2 = {
    "id": ex.LOC_B_FLOOR_2,
    "name": "Floor 2",
    "building": "B Block",
    "floor": "2",
    "description": "Offices B201-B230 and the floor 2 wiring closet",
    "parent_id": ex.LOC_B_BLOCK,
    "path": "Main campus / B Block / Floor 2",
    "device_count": 4,
}
_B_BLOCK = {
    "id": ex.LOC_B_BLOCK,
    "name": "B Block",
    "building": "B Block",
    "floor": None,
    "description": None,
    "parent_id": ex.LOC_CAMPUS,
    "path": "Main campus / B Block",
    "device_count": 1,
}


class Location(ApiModel):
    model_config = example(_FLOOR_2)

    id: UUID
    name: str
    building: str | None
    floor: str | None
    description: str | None
    parent_id: UUID | None
    path: str = Field(description="Full path from the top-level location, for display.")
    device_count: int = Field(ge=0, description="Devices directly in this location.")


class LocationCreate(ApiModel):
    model_config = example(
        {
            "name": "Floor 3",
            "building": "B Block",
            "floor": "3",
            "description": "Offices B301-B330",
            "parent_id": ex.LOC_B_BLOCK,
        }
    )

    name: str = Field(min_length=1, max_length=200)
    building: str | None = None
    floor: str | None = None
    description: str | None = None
    parent_id: UUID | None = None


class LocationUpdate(ApiModel):
    """Partial update: only the fields present in the body change."""

    model_config = example({"description": "Offices B201-B232 after the renovation"})

    name: str | None = Field(default=None, min_length=1, max_length=200)
    building: str | None = None
    floor: str | None = None
    description: str | None = None
    parent_id: UUID | None = None


class LocationPage(Page[Location]):
    model_config = example(ex.page([_B_BLOCK, _FLOOR_2]))
