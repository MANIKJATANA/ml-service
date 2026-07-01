"""SQLAlchemy declarative base + shared metadata.

The ML service owns its own metadata DB (matches, per-school thresholds, student
reference-photo URIs). Schema is created **only** via Alembic migrations (working
rule; decisions/0007); ``Base.metadata.create_all`` is used only in test fixtures.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ML-service ORM models."""


metadata = Base.metadata
