"""Alembic migrations against a real TimescaleDB: round trip, hypertables, model parity."""

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import URL, Connection, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from netops.db.base import Base
from netops.db.timescale import CHUNK_INTERVAL, hypertable_of

pytestmark = pytest.mark.integration

EXPECTED_TABLES = set(Base.metadata.tables)
EXPECTED_HYPERTABLES = {
    table.name: spec for table in Base.metadata.tables.values() if (spec := hypertable_of(table))
}


async def _query(url: URL, sql: str) -> list[Any]:
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.connect() as connection:
        rows = (await connection.execute(text(sql))).all()
    await engine.dispose()
    return list(rows)


def query(url: URL, sql: str) -> list[Any]:
    return asyncio.run(_query(url, sql))


def public_tables(url: URL) -> set[str]:
    rows = query(
        url,
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema = 'public' AND table_name <> 'alembic_version'",
    )
    return {row.table_name for row in rows}


def test_upgrade_downgrade_upgrade(migrated_database: URL, alembic_config: Config) -> None:
    assert public_tables(migrated_database) == EXPECTED_TABLES

    command.downgrade(alembic_config, "base")
    assert public_tables(migrated_database) == set()
    assert query(migrated_database, "SELECT typname FROM pg_type WHERE typtype = 'e'") == []
    assert query(migrated_database, "SELECT extname FROM pg_extension") == [("plpgsql",)]

    command.upgrade(alembic_config, "head")
    assert public_tables(migrated_database) == EXPECTED_TABLES
    assert len(EXPECTED_HYPERTABLES) == 12


def test_hypertables_match_the_models(migrated_database: URL) -> None:
    rows = query(
        migrated_database,
        "SELECT hypertable_name, column_name, time_interval"
        " FROM timescaledb_information.dimensions WHERE hypertable_schema = 'public'",
    )
    actual = {row.hypertable_name: (row.column_name, row.time_interval) for row in rows}
    expected = {
        name: (spec.time_column, spec.chunk_interval) for name, spec in EXPECTED_HYPERTABLES.items()
    }
    assert actual == expected
    assert {interval for _, interval in actual.values()} == {CHUNK_INTERVAL}


def test_every_hypertable_has_its_retention_policy(migrated_database: URL) -> None:
    rows = query(
        migrated_database,
        "SELECT hypertable_name, (config ->> 'drop_after')::interval AS drop_after"
        " FROM timescaledb_information.jobs WHERE proc_name = 'policy_retention'",
    )
    actual = {row.hypertable_name: row.drop_after for row in rows}
    assert actual == {name: spec.retention for name, spec in EXPECTED_HYPERTABLES.items()}
    assert set(actual.values()) == {timedelta(days=30), timedelta(days=90)}


def test_models_match_the_migrated_schema(migrated_database: URL) -> None:
    """Same check as `alembic check`: autogenerate finds nothing to change."""

    def diff(connection: Connection) -> list[Any]:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return list(compare_metadata(context, Base.metadata))

    async def run() -> list[Any]:
        engine = create_async_engine(migrated_database, poolclass=NullPool)
        async with engine.connect() as connection:
            result = await connection.run_sync(diff)
        await engine.dispose()
        return result

    assert asyncio.run(run()) == []
