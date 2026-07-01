"""Alembic environment (async, asyncpg).

Reads the DB URL from ``ML_DATABASE_URL`` (never from a committed file or the ini)
and targets ``ml_service.db.base.Base.metadata``. Migrations are hand-authored
(working rule; decisions/0007) — autogenerate may be used as a drafting aid but
each version file is reviewed before it lands.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from ml_service.db.base import Base
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = os.environ.get("ML_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "ML_DATABASE_URL is not set (expected postgresql+asyncpg://...)"
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_type=True
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
