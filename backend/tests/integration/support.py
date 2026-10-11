"""Helpers for integration tests that work through netops' own settings (committed data)."""

import asyncio
import secrets
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from netops.auth.passwords import hash_password
from netops.core.secrets import Secret
from netops.core.settings import get_settings
from netops.db import models as m
from netops.db.enums import CredentialKind, UserRole
from netops.db.session import create_engine

FAKELAB_TOPOLOGY = Path(__file__).resolve().parents[3] / "lab" / "fakelab" / "topology.yaml"
USERNAME = "netops-ro"
PASSWORD = "pw-" + secrets.token_hex(8)  # random per run: no password literal in the repo
OUTDATED = "pw-" + secrets.token_hex(8)  # a profile tried first that no device accepts
FAKELAB_REQUEST = {"seeds": ["10.255.0.2"], "allowed_subnets": ["10.255.0.0/24"]}


class Recorder:
    """Stands in for the Celery task queue (netops.api.v1.common.get_task_queue)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __call__(self, task: str, *args: Any) -> None:
        self.calls.append((task, args))


def run[T](make: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run ``make(session)`` against the database the application settings point at."""

    async def main() -> T:
        engine = create_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await make(session)
        finally:
            await engine.dispose()

    return asyncio.run(main())


async def clear_inventory(session: AsyncSession) -> None:
    """Delete every device (cascading to interfaces, links and collection runs), discovery
    run, job, credential profile and user, for tests that need an empty inventory. The
    audit log stays: it is append-only."""
    for model in (m.DiscoveryRun, m.Job, m.Device, m.CredentialProfile, m.User):
        await session.execute(delete(model))
    await session.commit()


ADMIN = "test-admin"
ADMIN_PASSWORD = "admin pass phrase " + secrets.token_hex(6)  # random per run


async def add_user(
    session: AsyncSession,
    username: str,
    role: UserRole,
    password: str,
    *,
    mfa_secret: str | None = None,
    must_change_password: bool = False,
) -> uuid.UUID:
    """A user straight into the database (bypassing the policy checks of the API)."""
    user = m.User(
        id=uuid.uuid4(),
        username=username,
        display_name=username,
        role=role,
        password_hash=hash_password(password),
        mfa_enabled=mfa_secret is not None,
        mfa_secret=Secret(mfa_secret) if mfa_secret else None,
        must_change_password=must_change_password,
    )
    session.add(user)
    await session.commit()
    return user.id


def sign_in(client: TestClient, username: str, password: str) -> dict[str, Any]:
    """POST /auth/login (no MFA); sets the bearer header on ``client``."""
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["status"] == "authenticated", body
    client.headers["Authorization"] = f"Bearer {body['access_token']}"
    return body


async def create_lab_profiles(session: AsyncSession) -> list[uuid.UUID]:
    """An empty inventory and two SSH profiles: an outdated one first, then the lab's."""
    await clear_inventory(session)
    rows = [
        m.CredentialProfile(
            id=uuid.uuid4(),
            name=name,
            kind=CredentialKind.SSH,
            username=USERNAME,
            password=Secret(password),
        )
        for name, password in (("lab-outdated", OUTDATED), ("lab", PASSWORD))
    ]
    session.add_all(rows)
    await session.commit()
    return [row.id for row in rows]
