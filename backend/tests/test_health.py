"""GET /api/health with the database and Redis probes mocked out."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from netops import __version__
from netops.api import health


def _mock_probes(
    monkeypatch: pytest.MonkeyPatch, *, db_error: bool = False, redis_error: bool = False
) -> None:
    monkeypatch.setattr(
        health, "ping_database", AsyncMock(side_effect=OSError("db down") if db_error else None)
    )
    monkeypatch.setattr(
        health, "ping_redis", AsyncMock(side_effect=OSError("redis down") if redis_error else None)
    )


def test_health_ok(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_probes(monkeypatch)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "db": "ok", "redis": "ok"}


@pytest.mark.parametrize(
    ("db_error", "redis_error", "expected_db", "expected_redis"),
    [
        (True, False, "error", "ok"),
        (False, True, "ok", "error"),
        (True, True, "error", "error"),
    ],
)
def test_health_degraded(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    db_error: bool,
    redis_error: bool,
    expected_db: str,
    expected_redis: str,
) -> None:
    _mock_probes(monkeypatch, db_error=db_error, redis_error=redis_error)

    response = client.get("/api/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == expected_db
    assert body["redis"] == expected_redis


def test_health_probe_timeout_counts_as_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def hang() -> None:
        await asyncio.sleep(10)

    _mock_probes(monkeypatch)
    monkeypatch.setattr(health, "ping_database", hang)

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["db"] == "error"
    assert response.json()["redis"] == "ok"


def test_openapi_docs_are_served(client: TestClient) -> None:
    assert client.get("/api/docs").status_code == 200
    assert client.get("/api/openapi.json").json()["info"]["title"] == "NetOps Platform API"
