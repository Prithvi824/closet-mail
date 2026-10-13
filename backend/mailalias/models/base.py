"""Declarative base, shared column mixins and the Postgres enum helper."""

# 1st party imports
import uuid
from datetime import datetime
from enum import StrEnum

# 3rd party imports
from sqlalchemy import DateTime, Enum, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names so Alembic autogenerate and downgrades are stable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Root of all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: DateTime(timezone=True)}


class UUIDPrimaryKey:
    """Adds a random UUID primary key."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class Timestamps:
    """Adds created_at / updated_at maintained by the database and ORM."""

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


def pg_enum[E: StrEnum](enum_cls: type[E], name: str) -> Enum:
    """Map a StrEnum to a native Postgres enum storing the lowercase values.

    Args:
        enum_cls: The Python enum.
        name: Postgres type name.
    Returns:
        A SQLAlchemy Enum type.
    """
    return Enum(enum_cls, name=name, values_callable=lambda members: [m.value for m in members])
