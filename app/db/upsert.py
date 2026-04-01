"""Dialect-aware INSERT ... ON CONFLICT helper.

Production runs PostgreSQL; the component test suite runs SQLite (which has
supported ON CONFLICT and RETURNING for years). Both dialects expose the same
`on_conflict_do_nothing` / `on_conflict_do_update` API in SQLAlchemy.
"""
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession


def upsert_stmt(session: AsyncSession, table):
    dialect = session.bind.dialect.name
    if dialect == "postgresql":
        return pg_insert(table)
    if dialect == "sqlite":
        return sqlite_insert(table)
    raise NotImplementedError(f"no upsert support wired for dialect {dialect!r}")
