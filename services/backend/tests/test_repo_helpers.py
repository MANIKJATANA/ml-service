"""Unit tests for the repository helpers (decisions/0023 review fixes)."""

from __future__ import annotations

import uuid

import pytest
from backend.adapters.repositories._common import opt_uuid, req_uuid, violated_constraint
from backend.domain.errors import ValidationError
from sqlalchemy.exc import IntegrityError


def test_opt_uuid_parses_and_tolerates_garbage() -> None:
    u = uuid.uuid4()
    assert opt_uuid(str(u)) == u
    assert opt_uuid("not-a-uuid") is None  # malformed -> None (treated as not-found)


def test_req_uuid_parses_and_raises_on_garbage() -> None:
    u = uuid.uuid4()
    assert req_uuid(str(u), field="school_id") == u
    with pytest.raises(ValidationError):
        req_uuid("not-a-uuid", field="school_id")


class _RawDbError(Exception):
    """Stand-in for the raw asyncpg error, which carries ``constraint_name``."""

    def __init__(self, constraint_name: str) -> None:
        super().__init__("raw db error")
        self.constraint_name = constraint_name


def _integrity_error(*, on_orig: str | None, on_cause: str | None) -> IntegrityError:
    """Shape an IntegrityError like SQLAlchemy+asyncpg: ``exc.orig`` is a DBAPI
    wrapper whose ``__cause__`` is the raw driver error carrying constraint_name."""
    wrapper = Exception("dbapi wrapper (no constraint_name on asyncpg)")
    if on_orig is not None:
        wrapper.constraint_name = on_orig  # type: ignore[attr-defined]
    if on_cause is not None:
        wrapper.__cause__ = _RawDbError(on_cause)
    return IntegrityError("INSERT INTO users ...", None, wrapper)


def test_violated_constraint_reads_cause_chain() -> None:
    # SQLAlchemy+asyncpg: the name is on exc.orig.__cause__, not exc.orig — this is
    # the real stack shape, and the case the HIGH review finding turned on.
    exc = _integrity_error(on_orig=None, on_cause="uq_users_email")
    assert violated_constraint(exc) == "uq_users_email"


def test_violated_constraint_reads_orig_directly() -> None:
    # Future-proof: a driver that exposes it directly on orig.
    exc = _integrity_error(on_orig="uq_users_email", on_cause=None)
    assert violated_constraint(exc) == "uq_users_email"


def test_violated_constraint_none_when_absent() -> None:
    assert violated_constraint(_integrity_error(on_orig=None, on_cause=None)) is None
