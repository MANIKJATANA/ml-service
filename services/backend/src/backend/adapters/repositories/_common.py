"""Shared helpers for the Postgres repositories."""

from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError

from backend.domain.errors import ValidationError


def opt_uuid(value: str) -> uuid.UUID | None:
    """Parse a UUID string; return None if malformed (treated as 'not found')."""
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def req_uuid(value: str, *, field: str) -> uuid.UUID:
    """Parse a UUID string; raise ValidationError (HTTP 400) if malformed."""
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ValidationError(f"invalid {field}: {value!r}") from exc


def violated_constraint(exc: IntegrityError) -> str | None:
    """The DB constraint name behind an IntegrityError, if the driver exposes it.

    For the SQLAlchemy + asyncpg stack ``exc.orig`` is a DBAPI *wrapper* that does
    NOT carry ``constraint_name``; the raw asyncpg error that does is one level
    deeper at ``exc.orig.__cause__``. Check ``orig`` first (future-proof / other
    drivers), then the cause. Returns None if unavailable.
    """
    orig = getattr(exc, "orig", None)
    name = getattr(orig, "constraint_name", None) or getattr(
        getattr(orig, "__cause__", None), "constraint_name", None
    )
    return name if isinstance(name, str) else None
