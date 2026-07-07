"""SQLAlchemy declarative base for the backend's own tables.

The backend owns its identity/PII schema (schools, users, students, events, media).
Schema is created **only** via Alembic migrations (working rule; decisions/0007);
``Base.metadata.create_all`` is used only in test fixtures. The base holds
backend-owned tables only — never the ML-owned tables the backend reads.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all backend ORM models."""


metadata = Base.metadata
