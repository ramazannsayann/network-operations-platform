"""Host locator (M6)."""

from typing import Annotated, Any

from fastapi import APIRouter, Query

from netops.api.problems import not_implemented, problems
from netops.api.schemas.hosts import FOUND_EXAMPLE, NOT_FOUND_EXAMPLE, HostLocateResult
from netops.api.security import AUTHENTICATED
from netops.api.v1.common import At

router = APIRouter(
    prefix="/hosts", tags=["hosts"], dependencies=AUTHENTICATED, responses=problems(401, 422, 501)
)

_EXAMPLES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Where the host is, or why it could not be found.",
        "content": {
            "application/json": {
                "examples": {
                    "found": {"summary": "Wired host found", "value": FOUND_EXAMPLE},
                    "not_found": {"summary": "Host not found", "value": NOT_FOUND_EXAMPLE},
                }
            }
        },
    }
}


@router.get("/locate", responses=_EXAMPLES, response_model=HostLocateResult)
async def locate_host(
    query: Annotated[
        str,
        Query(
            min_length=1,
            max_length=64,
            description="IPv4/IPv6 address, or MAC address in any common notation "
            "(aa:bb:cc:dd:ee:ff, aa-bb-cc-dd-ee-ff, aabb.ccdd.eeff).",
            examples=["10.0.20.57"],
        ),
    ],
    at: At = None,
    refresh: Annotated[
        bool,
        Query(
            description="Ping the host from its gateway and re-read the ARP/MAC tables "
            "before answering (proposal 7.6). Only allowed without `at`."
        ),
    ] = False,
) -> Any:
    """Find the edge port (device, interface, VLAN, location) a host is connected to.

    A host that cannot be located is a normal result (``status: not_found`` with a
    ``reason``), not a 404.
    """
    raise not_implemented()
