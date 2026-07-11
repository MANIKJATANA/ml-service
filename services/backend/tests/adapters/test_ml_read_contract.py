"""Contract test guarding the Phase-6 read coupling (decisions/0028, 0029).

`backend.db.ml_read.matches` hard-codes the subset of the ML service's `matches`
columns the backend reads. If an ML schema change drops or renames one, backend
gallery reads break at runtime. Two guards:

- `test_matches_columns_match_ml_model` — **always runs, no DB.** Compares the
  backend mapping to the ML service's authoritative ORM model (`ml_service.db.models`),
  so ML model drift fails backend CI on every push. (The import is light —
  `ml_service.db.models` pulls in only SQLAlchemy + the declarative base.)
- `test_matches_columns_exist_in_live_schema` — **gated on BE_TEST_DATABASE_URL.**
  Checks a live Postgres `matches` via `information_schema` (honors decisions/0028):
  every consumed column exists with a compatible Postgres `data_type`, so it also
  validates that the `ml_read.py` SQLAlchemy types realize the way ML's model does.
  It self-provisions the table from ML's `Match` model when absent and drops only
  what it created — so, like every gated test here, it assumes a disposable test DB.
"""

from __future__ import annotations

import os
from typing import cast

import pytest
import sqlalchemy as sa
from backend.db.ml_read import matches
from ml_service.db.models import Match

# Match.__table__ is typed as FromClause by the SQLAlchemy stubs; at runtime it is the
# Table, which is what create()/drop() need.
_ML_MATCHES = cast(sa.Table, Match.__table__)


def _family(coltype: object) -> str:
    """Coarse type family, comparable across generic + dialect SQLAlchemy types."""
    if isinstance(coltype, sa.Uuid) or "uuid" in type(coltype).__name__.lower():
        return "uuid"
    if isinstance(coltype, sa.Boolean):
        return "bool"
    if isinstance(coltype, (sa.Float, sa.Numeric)):
        return "number"
    if isinstance(coltype, sa.Integer):
        return "int"
    if isinstance(coltype, sa.String):
        return "string"
    return type(coltype).__name__.lower()


def test_matches_columns_match_ml_model() -> None:
    ml_cols = _ML_MATCHES.columns
    for col in matches.columns:
        assert col.name in ml_cols, (
            f"ml_read.matches reads column {col.name!r} that ML's Match model no "
            f"longer defines — the Phase-6 read coupling is broken."
        )
        assert _family(col.type) == _family(ml_cols[col.name].type), (
            f"column {col.name!r} type family drifted: backend {_family(col.type)} "
            f"vs ML {_family(ml_cols[col.name].type)}"
        )


def test_family_covers_every_type_branch() -> None:
    # Locks the helper's contract. The int/number branches aren't hit by today's
    # matches columns but back the gated live-schema check's _PG_TYPES lookup.
    assert _family(sa.Uuid()) == "uuid"
    assert _family(sa.String()) == "string"
    assert _family(sa.Float()) == "number"
    assert _family(sa.Numeric()) == "number"
    assert _family(sa.Boolean()) == "bool"
    assert _family(sa.Integer()) == "int"


# Postgres data_type (information_schema) values accepted per family.
_PG_TYPES = {
    "uuid": {"uuid"},
    "bool": {"boolean"},
    "number": {"double precision", "real", "numeric"},
    "int": {"integer", "bigint", "smallint"},
    "string": {"character varying", "text", "character"},
}

_DSN = os.environ.get("BE_TEST_DATABASE_URL")


@pytest.mark.skipif(_DSN is None, reason="BE_TEST_DATABASE_URL not set")
async def test_matches_columns_exist_in_live_schema() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    assert _DSN is not None
    query = text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'matches'"
    )
    engine = create_async_engine(_DSN)
    try:
        async with engine.connect() as conn:
            live = {r.column_name: r.data_type for r in await conn.execute(query)}

        # Bare DB (no ML chain applied): self-provision from ML's model, then drop.
        created = not live
        if created:
            async with engine.begin() as conn:
                await conn.run_sync(_ML_MATCHES.create)
            async with engine.connect() as conn:
                live = {r.column_name: r.data_type for r in await conn.execute(query)}

        try:
            for col in matches.columns:
                assert col.name in live, f"live matches is missing column {col.name!r}"
                accepted = _PG_TYPES[_family(col.type)]
                assert live[col.name] in accepted, (
                    f"{col.name!r}: live type {live[col.name]!r} not in {accepted}"
                )
        finally:
            if created:
                async with engine.begin() as conn:
                    await conn.run_sync(_ML_MATCHES.drop)
    finally:
        await engine.dispose()
