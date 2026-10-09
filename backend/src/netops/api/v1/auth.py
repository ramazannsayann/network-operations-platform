"""Authentication (M7, contract only)."""

from fastapi import APIRouter

from netops.api.problems import not_implemented, problems
from netops.api.schemas.auth import CurrentUser, LoginRequest, Token
from netops.api.security import AUTHENTICATED

router = APIRouter(prefix="/auth", tags=["auth"], responses=problems(422, 501))


@router.post("/login", responses=problems(401))
async def login(body: LoginRequest) -> Token:
    """Exchange username and password for a bearer token."""
    raise not_implemented()


@router.get("/me", dependencies=AUTHENTICATED, responses=problems(401))
async def get_current_user() -> CurrentUser:
    """The user the bearer token belongs to."""
    raise not_implemented()
