"""Shared fixtures. Tests never talk to a real database, Redis or network device."""

import os
import secrets
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

# Some netops modules read settings at import time, so these must be set before any
# test module imports them. Values here override the developer's shell and .env file.
os.environ["APP_ENV"] = "test"
os.environ["POSTGRES_PASSWORD"] = "test-only"  # noqa: S105 - dummy, never used to connect
os.environ["HEALTH_CHECK_TIMEOUT_SECONDS"] = "0.2"
# Fresh keys per test session: no key material is committed, even for tests.
os.environ["CREDENTIALS_KEY"] = Fernet.generate_key().decode()
os.environ["AUTH_SIGNING_KEY"] = secrets.token_urlsafe(48)


def principal(role: str = "admin", requirements: tuple[str, ...] = ()) -> Any:
    """A signed-in user for unit tests, which have no database to authenticate against."""
    from netops.api.security import Principal
    from netops.auth.service import Requirement
    from netops.db.enums import UserRole

    return Principal(
        user_id=uuid.UUID("5e0c7a1d-0000-4000-8000-000000007001"),
        username=f"test-{role}",
        role=UserRole(role),
        session_id=uuid.UUID("5e0c7a1d-0000-4000-8000-000000007101"),
        requirements=tuple(Requirement(r) for r in requirements),
        ip="127.0.0.1",
        user_agent="pytest",
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    """The API with an admin signed in (dependency override, no token or database)."""
    from netops.api.security import get_principal
    from netops.main import create_app

    app = create_app()
    app.dependency_overrides[get_principal] = lambda: principal()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def anonymous_client() -> Iterator[TestClient]:
    """The API as it is: requests without a valid token get 401."""
    from netops.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
