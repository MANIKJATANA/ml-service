"""Postgres repository adapters against a real database.

Set ``ML_TEST_DATABASE_URL`` (postgresql+asyncpg://...) to run; otherwise skipped.
The schema is created via ``Base.metadata.create_all`` in the fixture — allowed in
tests only (application code uses migrations; decisions/0007).
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from ml_service.adapters.repository.postgres_detections import (
    PostgresDetectionRepository,
)
from ml_service.adapters.repository.postgres_matches import PostgresMatchRepository
from ml_service.adapters.repository.postgres_reference_photos import (
    PostgresReferencePhotoRepository,
)
from ml_service.adapters.repository.postgres_thresholds import PostgresThresholdProvider
from ml_service.db.base import Base
from ml_service.db.models import (
    FaceDetection,
    FaceDetectionCandidate,
    Match,
    MediaDetection,
    SchoolThreshold,
)
from ml_service.domain.models import (
    DetectionCandidate,
    DetectionOutcome,
    FaceBox,
    FaceDetectionRecord,
    FrameDetectionRecord,
    MatchRecord,
    MediaDetectionRecord,
    MediaType,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DSN = os.environ.get("ML_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="ML_TEST_DATABASE_URL not set")


@pytest_asyncio.fixture
async def sessionmaker():  # type: ignore[no-untyped-def]
    engine = create_async_engine(DSN)  # type: ignore[arg-type]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _record(confidence: float, student: str = "alice") -> MatchRecord:
    return MatchRecord(
        school_id="s1",
        event_id="e1",
        student_id=student,
        media_id="m1",
        media_type=MediaType.IMAGE,
        confidence_score=confidence,
        needs_review=False,
        embedding_model_version="ev",
        detector_model_version="dv",
        threshold_used=0.5,
        gap_threshold_used=0.1,
    )


async def _confidence(sm: async_sessionmaker[AsyncSession], student: str = "alice") -> float:
    async with sm() as session:
        row = (
            await session.execute(
                select(Match.confidence_score).where(Match.student_id == student)
            )
        ).first()
    assert row is not None
    return float(row[0])


async def test_save_batch_idempotent_higher_wins(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    repo = PostgresMatchRepository(sessionmaker)
    await repo.save_batch([_record(0.70)])
    await repo.save_batch([_record(0.60)])  # lower — ignored
    assert await _confidence(sessionmaker) == pytest.approx(0.70)
    await repo.save_batch([_record(0.90)])  # higher — upgrades in place
    assert await _confidence(sessionmaker) == pytest.approx(0.90)
    assert await repo.exists("m1", "alice")
    assert not await repo.exists("m1", "ghost")


async def test_thresholds_fallback_and_override(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    provider = PostgresThresholdProvider(
        sessionmaker, default_match_confidence=0.65, default_gap=0.08
    )
    # No row → global defaults.
    th = await provider.get_thresholds("s-none")
    assert th.match_confidence == pytest.approx(0.65)
    assert th.gap == pytest.approx(0.08)
    # Row with a partial override → override wins, null falls back.
    async with sessionmaker() as session, session.begin():
        session.add(
            SchoolThreshold(
                school_id="s-ovr", match_confidence_threshold=0.8, gap_threshold=None
            )
        )
    provider2 = PostgresThresholdProvider(
        sessionmaker, default_match_confidence=0.65, default_gap=0.08
    )
    th2 = await provider2.get_thresholds("s-ovr")
    assert th2.match_confidence == pytest.approx(0.8)
    assert th2.gap == pytest.approx(0.08)


async def test_reference_photos_replace_and_delete(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    repo = PostgresReferencePhotoRepository(sessionmaker)
    assert await repo.get("s1", "alice") == []
    await repo.replace("s1", "alice", ["u1", "u2", "u3"])
    assert await repo.get("s1", "alice") == ["u1", "u2", "u3"]  # order preserved
    await repo.replace("s1", "alice", ["only"])  # replace, not append
    assert await repo.get("s1", "alice") == ["only"]
    await repo.delete("s1", "alice")
    assert await repo.get("s1", "alice") == []


def _detection_record(media_id: str, students: list[str]) -> MediaDetectionRecord:
    faces = tuple(
        FaceDetectionRecord(
            face_index=i,
            box=FaceBox(0.0, 0.0, 10.0, 10.0, 0.99),
            outcome=DetectionOutcome.MATCH,
            candidates=(DetectionCandidate(s, 0.9, 1, True, True, False),),
        )
        for i, s in enumerate(students)
    )
    frame = FrameDetectionRecord(frame_index=0, frame_timestamp_ms=None, faces=faces)
    return MediaDetectionRecord(
        school_id="s1",
        event_id="e1",
        media_id=media_id,
        media_type=MediaType.IMAGE,
        media_uri="u",
        video_fps=None,
        frames_sampled=1,
        faces_detected=len(students),
        candidates_above_threshold=len(students),
        unknown_faces=0,
        matches_emitted=len(students),
        ambiguous_matches=0,
        top_k=2,
        match_confidence_threshold=0.5,
        gap_threshold=0.1,
        embedding_model_version="ev",
        detector_model_version="dv",
        processing_ms=5,
        frames=(frame,),
    )


async def _count(sm: async_sessionmaker[AsyncSession], model: type) -> int:
    async with sm() as session:
        return len((await session.execute(select(model))).scalars().all())


async def test_detection_replace_by_media_and_cascade(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    repo = PostgresDetectionRepository(sessionmaker)
    await repo.save_detections(_detection_record("m1", ["alice", "bob"]))
    assert await _count(sessionmaker, MediaDetection) == 1
    assert await _count(sessionmaker, FaceDetection) == 2
    assert await _count(sessionmaker, FaceDetectionCandidate) == 2

    # Reprocess with a different result: replace-by-media (FK cascade wipes the old
    # tree), never a duplicate media row.
    await repo.save_detections(_detection_record("m1", ["carol"]))
    assert await _count(sessionmaker, MediaDetection) == 1
    assert await _count(sessionmaker, FaceDetection) == 1
    assert await _count(sessionmaker, FaceDetectionCandidate) == 1
    async with sessionmaker() as session:
        rows = (await session.execute(select(FaceDetectionCandidate))).scalars().all()
    assert rows[0].student_id == "carol"
