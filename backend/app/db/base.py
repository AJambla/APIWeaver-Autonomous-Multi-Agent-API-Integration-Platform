"""Declarative base, naming conventions, and shared column mixins.

The naming convention matters: without it Alembic autogenerate produces migrations with
database-assigned constraint names, which makes `downgrade()` unable to drop them by
name. `Database.md §6` requires every migration to ship a working downgrade.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, MetaData
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import expression
from sqlalchemy.types import TypeDecorator, TypeEngine

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


# --- Dialect-aware server defaults ---------------------------------------------------
# Production is Postgres-only, but the test suite runs on aiosqlite for speed. These
# compile to the native function on each dialect so the models can declare a server
# default once instead of branching per dialect at every column.


class gen_random_uuid(expression.FunctionElement[uuid.UUID]):  # noqa: N801 — SQL function name
    """`gen_random_uuid()` — built into Postgres 13+, so no extension needed."""

    type = postgresql.UUID(as_uuid=True)
    inherit_cache = True
    name = "gen_random_uuid"


@compiles(gen_random_uuid)  # type: ignore[no-untyped-call]
def _gen_random_uuid_default(element: Any, compiler: Any, **kw: Any) -> str:
    return "gen_random_uuid()"


@compiles(gen_random_uuid, "sqlite")  # type: ignore[no-untyped-call]
def _gen_random_uuid_sqlite(element: Any, compiler: Any, **kw: Any) -> str:
    """UUIDv4-shaped string from `randomblob`.

    Only reached in tests, and only for inserts that bypass the ORM — every model also
    carries a client-side `default=uuid.uuid4`, which takes precedence.
    """
    return (
        "lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' "
        "|| substr(hex(randomblob(2)),2) || '-' "
        "|| substr('89ab',abs(random())%4+1,1) || substr(hex(randomblob(2)),2) || '-' "
        "|| hex(randomblob(6)))"
    )


class utcnow(expression.FunctionElement[datetime.datetime]):  # noqa: N801 — SQL function name
    """`now()` on Postgres, `CURRENT_TIMESTAMP` elsewhere."""

    # The plain impl, not TZDateTime: this is the DDL-level default expression, and
    # TZDateTime is defined below anyway.
    type = DateTime(timezone=True)
    inherit_cache = True
    name = "utcnow"


@compiles(utcnow)  # type: ignore[no-untyped-call]
def _utcnow_default(element: Any, compiler: Any, **kw: Any) -> str:
    return "now()"


@compiles(utcnow, "sqlite")  # type: ignore[no-untyped-call]
def _utcnow_sqlite(element: Any, compiler: Any, **kw: Any) -> str:
    return "CURRENT_TIMESTAMP"


class false_(expression.FunctionElement[bool]):  # noqa: N801 — SQL literal
    """Boolean false literal; SQLite has no boolean type, so it needs `0`."""

    type = postgresql.BOOLEAN()
    inherit_cache = True
    name = "false_"


@compiles(false_)  # type: ignore[no-untyped-call]
def _false_default(element: Any, compiler: Any, **kw: Any) -> str:
    return "false"


@compiles(false_, "sqlite")  # type: ignore[no-untyped-call]
def _false_sqlite(element: Any, compiler: Any, **kw: Any) -> str:
    return "0"


class TZDateTime(TypeDecorator[datetime.datetime]):
    """Timezone-aware datetime that stays aware on the way back out.

    Postgres `TIMESTAMPTZ` returns aware datetimes, but SQLite has no timezone type and
    hands back naive ones — so a comparison against `datetime.now(UTC)` raises
    `TypeError` under the test dialect while working in production. Normalizing here means
    application code can assume aware datetimes on every dialect, rather than every
    comparison site having to defend itself.
    """

    impl = DateTime
    cache_ok = True

    def __init__(self) -> None:
        super().__init__(timezone=True)

    def process_bind_param(
        self, value: datetime.datetime | None, dialect: Any
    ) -> datetime.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            # Treat a naive input as UTC rather than local time — the server's local zone
            # is not a meaningful default and would silently shift stored instants.
            return value.replace(tzinfo=datetime.UTC)
        return value.astimezone(datetime.UTC)

    def process_result_value(
        self, value: datetime.datetime | None, dialect: Any
    ) -> datetime.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=datetime.UTC)
        return value.astimezone(datetime.UTC)


class JSONB(TypeDecorator[Any]):
    """`JSONB` on Postgres, plain `JSON` elsewhere.

    The tests run on aiosqlite for speed; production is Postgres-only. This keeps the
    models declarable once instead of branching per dialect at every column.
    """

    impl = postgresql.JSONB
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB())
        from sqlalchemy import JSON

        return dialect.type_descriptor(JSON())


class UUID(TypeDecorator[uuid.UUID]):
    """Native `UUID` on Postgres, 36-char text elsewhere."""

    impl = postgresql.UUID
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.UUID(as_uuid=True))
        from sqlalchemy import String

        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None or dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value: Any, dialect: Any) -> uuid.UUID | None:
        if value is None or isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class INET(TypeDecorator[str]):
    """`INET` on Postgres, text elsewhere."""

    impl = postgresql.INET
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.INET())
        from sqlalchemy import String

        return dialect.type_descriptor(String(45))


def bigint_pk() -> Mapped[int]:
    """`BIGSERIAL` primary key.

    The `sqlite` variant matters: SQLite only auto-increments a column declared exactly
    `INTEGER PRIMARY KEY`, so a `BIGINT` PK there is `NOT NULL` with no generator and
    every insert fails. On Postgres this is `BIGSERIAL` as `Database.md §3.17` specifies.
    """
    return mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
        sort_order=-100,
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {
        uuid.UUID: UUID(),
        dict[str, Any]: JSONB(),
        datetime.datetime: TZDateTime(),
    }


def uuid_pk() -> Mapped[uuid.UUID]:
    """UUID primary key generated by the database (`Database.md §3`, `gen_random_uuid()`).

    Server-side generation keeps the ID authoritative in one place; `gen_random_uuid()`
    is built into Postgres 13+ so no extension is required.
    """
    return mapped_column(
        UUID(),
        primary_key=True,
        server_default=gen_random_uuid(),
        default=uuid.uuid4,  # so aiosqlite-backed tests get an ID too
        # Mixin columns otherwise sort after the model's own; keep `id` first and the
        # timestamps last so the physical column order reads like Database.md §3.
        sort_order=-100,
    )


class UUIDPrimaryKeyMixin:
    """`id UUID PK DEFAULT gen_random_uuid()`."""

    id: Mapped[uuid.UUID] = uuid_pk()


class CreatedAtMixin:
    """`created_at TIMESTAMPTZ NOT NULL DEFAULT now()`."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        TZDateTime(),
        nullable=False,
        server_default=utcnow(),
        default=lambda: datetime.datetime.now(datetime.UTC),
        sort_order=100,
    )


class TimestampMixin(CreatedAtMixin):
    """Adds `updated_at`, bumped by the ORM on flush."""

    updated_at: Mapped[datetime.datetime] = mapped_column(
        TZDateTime(),
        nullable=False,
        server_default=utcnow(),
        default=lambda: datetime.datetime.now(datetime.UTC),
        onupdate=lambda: datetime.datetime.now(datetime.UTC),
        sort_order=101,
    )
