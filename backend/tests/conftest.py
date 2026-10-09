"""Shared fixtures. Tests never talk to a real database, Redis or network device."""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

# Some netops modules read settings at import time, so these must be set before any
# test module imports them. Values here override the developer's shell and .env file.
os.environ["APP_ENV"] = "test"
os.environ["POSTGRES_PASSWORD"] = "test-only"  # noqa: S105 - dummy, never used to connect
os.environ["HEALTH_CHECK_TIMEOUT_SECONDS"] = "0.2"


@pytest.fixture
def client() -> Iterator[TestClient]:
    from netops.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
