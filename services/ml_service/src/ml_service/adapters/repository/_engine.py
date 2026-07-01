"""Shared async SQLAlchemy engine/session helpers for the Postgres adapters.

The DSN uses the asyncpg driver, e.g.
``postgresql+asyncpg://user:pass@host:5432/db``. The password is a secret
supplied by wiring (Phase 3) from the environment — never stored in code.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(dsn: str, *, echo: bool = False) -> AsyncEngine:
    return create_async_engine(dsn, echo=echo, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
