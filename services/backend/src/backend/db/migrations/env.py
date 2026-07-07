"""Alembic environment (async, asyncpg) for the backend DB.

Reads the DB URL from ``BE_DATABASE_URL`` (never from a committed file or the ini)
and targets ``backend.db.base.Base.metadata``. Uses a **distinct version table**,
``alembic_version_backend``, so this chain coexists with the ML chain in the same
database without clobbering its bookkeeping (decisions/0022, 0023). Migrations are
hand-authored (working rule; decisions/0007).
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from backend.db import models  # noqa: F401
from backend.db.base import Base
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# `models` is imported above so every table is registered here — keeps
# autogenerate honest. Hand-authored `upgrade head` does not require it.
target_metadata = Base.metadata

# Distinct from the ML chain's default ``alembic_version`` — both live in one DB.
_VERSION_TABLE = "alembic_version_backend"


def _database_url() -> str:
    url = os.environ.get("BE_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "BE_DATABASE_URL is not set (expected postgresql+asyncpg://...)"
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        version_table=_VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        version_table=_VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
