"""Integration tests against a real TimescaleDB on localhost (the compose ``db`` service).

Run them with ``make test-integration`` after ``make up``. They work in a database of their
own, TEST_POSTGRES_DB (default ``netops_test``), which is dropped and recreated once per
test session, so the application database is never touched. Connections to anything but
127.0.0.1 / ::1 are blocked by pytest-socket.
"""

import asyncio
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from netops.api.v1.common import get_task_queue
from netops.core.settings import get_settings
from netops.db.session import create_engine, get_engine, get_sessionmaker
from netops.discovery.engine import run_discovery
from netops_fakes.local import LocalLab
from netops_fakes.topology import load
from tests.integration.support import (
    FAKELAB_REQUEST,
    FAKELAB_TOPOLOGY,
    PASSWORD,
    USERNAME,
    Recorder,
    clear_inventory,
    create_lab_profiles,
    run,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]
LOCAL_HOSTS = ["127.0.0.1", "::1"]


class IntegrationDatabase(BaseSettings):
    """Where the integration tests may create their database (TEST_POSTGRES_* variables)."""

    model_config = SettingsConfigDict(env_prefix="TEST_POSTGRES_")

    host: str = "127.0.0.1"
    port: int = 5433
    user: str = "netops"
    password: SecretStr
    db: str = "netops_test"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # Lift --disable-socket for integration tests, but only towards the local database.
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(pytest.mark.allow_hosts(LOCAL_HOSTS))


async def _recreate_database(url: URL) -> None:
    admin = create_async_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    async with admin.connect() as connection:
        # The name is validated by the fixture below; identifiers cannot be bind parameters.
        await connection.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        await connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    await admin.dispose()


@pytest.fixture(scope="session")
def database_url() -> URL:
    """A freshly created, empty test database (not yet migrated)."""
    try:
        settings = IntegrationDatabase()
    except ValidationError:
        pytest.fail("TEST_POSTGRES_PASSWORD is not set; run `make test-integration`.")
    if settings.host not in LOCAL_HOSTS:
        pytest.fail(f"Integration tests only run against localhost, not {settings.host!r}.")
    if not re.fullmatch(r"[a-z0-9_]+_test", settings.db):
        pytest.fail(f"TEST_POSTGRES_DB must be a lower-case name ending in _test: {settings.db!r}")
    url = URL.create(
        "postgresql+asyncpg",
        username=settings.user,
        password=settings.password.get_secret_value(),
        host=settings.host,
        port=settings.port,
        database=settings.db,
    )
    asyncio.run(_recreate_database(url))
    return url


@pytest.fixture(scope="session")
def alembic_config(database_url: URL) -> Config:
    """Alembic configuration that migrates the test database instead of the app database."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def migrated_database(database_url: URL, alembic_config: Config) -> URL:
    """The test database upgraded to the latest Alembic revision."""
    command.upgrade(alembic_config, "head")
    return database_url


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def session(migrated_database: URL) -> AsyncIterator[AsyncSession]:
    """A session inside a transaction that is rolled back after the test."""
    engine = create_engine(migrated_database, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as db_session:
            yield db_session
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture
def app_on_test_database(monkeypatch: pytest.MonkeyPatch, migrated_database: URL) -> Iterator[None]:
    """Point netops' own settings (used by tasks and the API) at the test database."""
    for name, value in {
        "POSTGRES_HOST": migrated_database.host,
        "POSTGRES_PORT": migrated_database.port,
        "POSTGRES_USER": migrated_database.username,
        "POSTGRES_PASSWORD": migrated_database.password,
        "POSTGRES_DB": migrated_database.database,
        "SSH_RETRIES": 0,
        "SSH_CONNECT_TIMEOUT_SECONDS": 5,
    }.items():
        monkeypatch.setenv(name, str(value))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def profiles(app_on_test_database: None) -> Iterator[list[uuid.UUID]]:
    """Empty inventory + the fake lab's credential profiles [outdated, lab]; cleared after."""
    yield run(create_lab_profiles)
    run(clear_inventory)


@pytest.fixture
def api(profiles: list[uuid.UUID]) -> Iterator[tuple[TestClient, Recorder]]:
    """The application on the test database, with a recording task queue."""
    from netops.main import create_app

    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    recorder = Recorder()
    app = create_app()
    app.dependency_overrides[get_task_queue] = lambda: recorder
    with TestClient(app) as client:
        yield client, recorder
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@pytest.fixture
def discovered(
    api: tuple[TestClient, Recorder], profiles: list[uuid.UUID]
) -> tuple[TestClient, Recorder, dict[str, Any]]:
    """POST a discovery run, then execute the queued task here against the fake lab."""
    client, recorder = api
    response = client.post(
        "/api/v1/discovery/runs",
        json=FAKELAB_REQUEST | {"credential_profile_ids": [str(p) for p in profiles]},
    )
    assert response.status_code == 202, response.text
    job = response.json()
    ((task, (run_id,)),) = recorder.calls
    assert task == "netops.discover"
    assert job["target_href"] == f"/api/v1/discovery/runs/{run_id}"
    assert response.headers["location"] == job["href"] == f"/api/v1/jobs/{job['id']}"

    with LocalLab(load(FAKELAB_TOPOLOGY), USERNAME, PASSWORD) as lab:
        asyncio.run(run_discovery(uuid.UUID(run_id), get_settings(), lab.resolve))
    return client, recorder, job
