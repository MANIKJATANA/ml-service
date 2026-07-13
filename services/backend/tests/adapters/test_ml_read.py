"""Gated Postgres test for the ML-results reader (decisions/0028).

Reads the ML-owned ``matches`` table. Self-contained: it stands up the read-only
``matches`` mapping via ``ml_read_metadata.create_all`` (the reader consumes exactly
those columns), so it runs without the ML Alembic chain. Skipped without
BE_TEST_DATABASE_URL, like the other gated PG tests.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from backend.adapters.repositories.ml_results import PostgresMlResultsReader
from backend.db.ml_read import matches, ml_read_metadata
from backend.db.session import make_engine, make_sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_DSN = os.environ.get("BE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(_DSN is None, reason="BE_TEST_DATABASE_URL not set")


@pytest.fixture
async def sm() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    assert _DSN is not None
    engine = make_engine(_DSN)
    async with engine.begin() as conn:
        await conn.run_sync(ml_read_metadata.drop_all)
        await conn.run_sync(ml_read_metadata.create_all)
    try:
        yield make_sessionmaker(engine)
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(ml_read_metadata.drop_all)
        await engine.dispose()


async def _insert(
    sm: async_sessionmaker[AsyncSession],
    *,
    school_id: str,
    event_id: str,
    student_id: str,
    media_id: str,
    confidence: float = 0.9,
    needs_review: bool = False,
) -> None:
    async with sm() as session, session.begin():
        await session.execute(
            matches.insert().values(
                match_id=uuid.uuid4(),
                school_id=school_id,
                event_id=event_id,
                student_id=student_id,
                media_id=media_id,
                confidence_score=confidence,
                needs_review=needs_review,
            )
        )


async def test_reader_fans_out_and_is_tenant_scoped(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # School A, event e1: s1 in m1 & m2; s2 in m1. School B is noise on the same ids.
    await _insert(sm, school_id="A", event_id="e1", student_id="s1", media_id="m1")
    await _insert(sm, school_id="A", event_id="e1", student_id="s1", media_id="m2")
    await _insert(sm, school_id="A", event_id="e1", student_id="s2", media_id="m1")
    await _insert(sm, school_id="B", event_id="e1", student_id="s1", media_id="m1")
    reader = PostgresMlResultsReader(sm)

    ev = await reader.list_event_appearances("A", "e1")
    assert {(a.student_id, a.media_id) for a in ev} == {
        ("s1", "m1"),
        ("s1", "m2"),
        ("s2", "m1"),
    }

    st = await reader.list_student_appearances("A", "s1")
    assert {a.media_id for a in st} == {"m1", "m2"}  # B's row excluded by school

    md = await reader.list_media_appearances("A", "m1")
    assert {a.student_id for a in md} == {"s1", "s2"}  # B's row excluded by school


async def test_reader_carries_decision_facts(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    await _insert(
        sm, school_id="A", event_id="e1", student_id="s1", media_id="m1",
        confidence=0.71, needs_review=True,
    )
    reader = PostgresMlResultsReader(sm)
    appearances = await reader.list_media_appearances("A", "m1")
    assert len(appearances) == 1
    assert appearances[0].confidence == pytest.approx(0.71)
    assert appearances[0].needs_review is True


async def test_count_needs_review_is_tenant_scoped(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # School A: two matches, one flagged. School B: one flagged (noise on the same ids).
    await _insert(sm, school_id="A", event_id="e1", student_id="s1", media_id="m1",
                  needs_review=True)
    await _insert(sm, school_id="A", event_id="e1", student_id="s2", media_id="m1",
                  needs_review=False)
    await _insert(sm, school_id="B", event_id="e1", student_id="s1", media_id="m1",
                  needs_review=True)
    reader = PostgresMlResultsReader(sm)

    assert await reader.count_needs_review("A") == 1  # B's flagged row excluded
    assert await reader.count_needs_review("B") == 1
    assert await reader.count_needs_review("Z") == 0  # no rows for this school
