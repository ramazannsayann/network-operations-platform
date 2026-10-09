"""Declarative base that every ORM model inherits from."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, MetaData, Text
from sqlalchemy.orm import DeclarativeBase

from netops.db.enums import ALL_ENUMS, pg_type_name

# Deterministic constraint names, so Alembic can generate (and later drop) them reliably.
# Multi-column unique constraints and all indexes are named explicitly in the models.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _enum_values(enum_cls: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_cls]


def pg_enum(enum_cls: type[StrEnum]) -> Enum:
    """Native PostgreSQL enum storing the members' values (not their Python names)."""
    return Enum(
        enum_cls,
        name=pg_type_name(enum_cls),
        values_callable=_enum_values,
        validate_strings=True,
    )


class Base(DeclarativeBase):
    """Base class for ORM models. Every model module is imported in netops.db.models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # Python annotation -> column type defaults: every datetime is timestamptz (stored in
    # UTC), every str is unbounded text, and each StrEnum maps to its PostgreSQL enum.
    type_annotation_map: dict[Any, Any] = {  # noqa: RUF012 - SQLAlchemy reads it once
        datetime: DateTime(timezone=True),
        str: Text(),
        **{enum_cls: pg_enum(enum_cls) for enum_cls in ALL_ENUMS},
    }
