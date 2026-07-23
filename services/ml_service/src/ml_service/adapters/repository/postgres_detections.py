"""Postgres ``DetectionRepository`` (SQLAlchemy 2.x async) — the per-face audit sink.

``save_detections`` replaces every row for a media (decisions/0021): a per-``media_id``
advisory lock serializes concurrent reprocessing, then a ``DELETE`` on
``media_detections`` (FK ``ON DELETE CASCADE`` wipes the frames/faces/candidates) and a
bulk insert of the freshly-computed tree — all in one transaction. This is a *second*
idempotency model alongside the ``matches`` higher-confidence-wins upsert; both write
paths are independently idempotent, so a partial job failure self-heals on retry.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ml_service.db.models import (
    FaceDetection,
    FaceDetectionCandidate,
    MediaDetection,
    MediaFrame,
)
from ml_service.domain.models import FaceBox, MediaDetectionRecord


def _bbox_json(box: FaceBox) -> dict[str, float]:
    return {"x1": box.x1, "y1": box.y1, "x2": box.x2, "y2": box.y2}


def _landmarks_json(box: FaceBox) -> list[list[float]] | None:
    if box.landmarks is None:
        return None
    return [[x, y] for x, y in box.landmarks]


class PostgresDetectionRepository:
    """Persists the full per-face detection audit to Postgres (replace-by-media)."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def save_detections(self, detection: MediaDetectionRecord) -> None:
        media_detection_id = uuid.uuid4()
        media_row: dict[str, object] = {
            "media_detection_id": media_detection_id,
            "media_id": detection.media_id,
            "school_id": detection.school_id,
            "event_id": detection.event_id,
            "media_type": detection.media_type.value,
            "media_uri": detection.media_uri,
            "video_fps": detection.video_fps,
            "frames_sampled": detection.frames_sampled,
            "faces_detected": detection.faces_detected,
            "candidates_above_threshold": detection.candidates_above_threshold,
            "unknown_faces": detection.unknown_faces,
            "matches_emitted": detection.matches_emitted,
            "ambiguous_matches": detection.ambiguous_matches,
            "top_k": detection.top_k,
            "match_confidence_threshold": detection.match_confidence_threshold,
            "gap_threshold": detection.gap_threshold,
            "embedding_model_version": detection.embedding_model_version,
            "detector_model_version": detection.detector_model_version,
            "processing_ms": detection.processing_ms,
        }

        frame_rows: list[dict[str, object]] = []
        face_rows: list[dict[str, object]] = []
        candidate_rows: list[dict[str, object]] = []
        for frame in detection.frames:
            frame_id = uuid.uuid4()
            frame_rows.append(
                {
                    "frame_id": frame_id,
                    "media_detection_id": media_detection_id,
                    "frame_index": frame.frame_index,
                    "frame_timestamp_ms": frame.frame_timestamp_ms,
                    "faces_detected": len(frame.faces),
                }
            )
            for face in frame.faces:
                detection_id = uuid.uuid4()
                face_rows.append(
                    {
                        "detection_id": detection_id,
                        "media_detection_id": media_detection_id,
                        "frame_id": frame_id,
                        "frame_index": frame.frame_index,
                        "frame_timestamp_ms": frame.frame_timestamp_ms,
                        "face_index": face.face_index,
                        "bbox": _bbox_json(face.box),
                        "detection_score": face.box.score,
                        "landmarks": _landmarks_json(face.box),
                        "outcome": face.outcome.value,
                    }
                )
                for cand in face.candidates:
                    candidate_rows.append(
                        {
                            "detection_id": detection_id,
                            "student_id": cand.student_id,
                            "score": cand.score,
                            "rank": cand.rank,
                            "cleared_threshold": cand.cleared_threshold,
                            "emitted": cand.emitted,
                            "needs_review": cand.needs_review,
                        }
                    )

        async with self._sessionmaker() as session, session.begin():
            # Serialize concurrent reprocessing of the same media (at-least-once
            # delivery can hand one media_id to two workers). Released at commit.
            await session.execute(
                select(func.pg_advisory_xact_lock(func.hashtext(detection.media_id)))
            )
            await session.execute(
                delete(MediaDetection).where(
                    MediaDetection.media_id == detection.media_id
                )
            )
            await session.execute(insert(MediaDetection), [media_row])
            if frame_rows:
                await session.execute(insert(MediaFrame), frame_rows)
            if face_rows:
                await session.execute(insert(FaceDetection), face_rows)
            if candidate_rows:
                await session.execute(insert(FaceDetectionCandidate), candidate_rows)

    async def delete_candidates_by_student(
        self, school_id: str, student_id: str
    ) -> None:
        """Purge a student's per-face candidate rows (BP8e erasure). The media-centric
        parents (media_detections/media_frames/face_detections) stay — they belong to the
        media, shared across students. ``student_id`` is globally unique, so no school join
        is needed; ``school_id`` is accepted for a tenant-shaped signature."""
        stmt = delete(FaceDetectionCandidate).where(
            FaceDetectionCandidate.student_id == student_id
        )
        async with self._sessionmaker() as session, session.begin():
            await session.execute(stmt)
