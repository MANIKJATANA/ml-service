"""ORM models for the ML-service metadata DB (requirements §10).

These mirror the Alembic migrations (``0001_initial`` + ``0002`` detection tables,
decisions/0021) exactly. Application code never issues DDL — it assumes the schema a
migration already established (decisions/0007). Columns follow the req §10 data
contracts, plus the per-face detection audit (decisions/0021).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ml_service.db.base import Base


class Match(Base):
    """A persisted (student, media) match (req §10.1)."""

    __tablename__ = "matches"

    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[str] = mapped_column(String, nullable=False)
    event_id: Mapped[str] = mapped_column(String, nullable=False)
    student_id: Mapped[str] = mapped_column(String, nullable=False)
    media_id: Mapped[str] = mapped_column(String, nullable=False)
    media_type: Mapped[str] = mapped_column(String, nullable=False)  # image | video
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    bbox: Mapped[dict[str, float] | None] = mapped_column(JSONB, nullable=True)
    frame_timestamp_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    embedding_model_version: Mapped[str] = mapped_column(String, nullable=False)
    detector_model_version: Mapped[str] = mapped_column(String, nullable=False)
    threshold_used: Mapped[float] = mapped_column(Float, nullable=False)
    gap_threshold_used: Mapped[float] = mapped_column(Float, nullable=False)
    # How many frames this student was emitted in (1 for an image); decisions/0021.
    frames_matched: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # (media_id, student_id) unique = idempotency guard (NFR-5).
        UniqueConstraint("media_id", "student_id", name="uq_matches_media_student"),
        Index("ix_matches_school_event", "school_id", "event_id"),
        Index("ix_matches_school_student", "school_id", "student_id"),
    )


class SchoolThreshold(Base):
    """Per-school threshold overrides (req §10.2). Null → global default from
    config, resolved by the ``ThresholdProvider`` adapter."""

    __tablename__ = "school_thresholds"

    school_id: Mapped[str] = mapped_column(String, primary_key=True)
    match_confidence_threshold: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    gap_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)


class StudentReferencePhoto(Base):
    """Reference-photo URIs backing student-id-triggered enrollment
    (decisions/0009)."""

    __tablename__ = "student_reference_photos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    school_id: Mapped[str] = mapped_column(String, nullable=False)
    student_id: Mapped[str] = mapped_column(String, nullable=False)
    photo_uri: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_srp_school_student", "school_id", "student_id"),
    )


class MediaDetection(Base):
    """Media-level detection summary (decisions/0021) — one row per processed media,
    the root of the per-face detection audit tree (replace-by-media)."""

    __tablename__ = "media_detections"

    media_detection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    media_id: Mapped[str] = mapped_column(String, nullable=False)
    school_id: Mapped[str] = mapped_column(String, nullable=False)
    event_id: Mapped[str] = mapped_column(String, nullable=False)
    media_type: Mapped[str] = mapped_column(String, nullable=False)  # image | video
    media_uri: Mapped[str] = mapped_column(String, nullable=False)
    video_fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    frames_sampled: Mapped[int] = mapped_column(Integer, nullable=False)
    faces_detected: Mapped[int] = mapped_column(Integer, nullable=False)
    candidates_above_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    unknown_faces: Mapped[int] = mapped_column(Integer, nullable=False)
    matches_emitted: Mapped[int] = mapped_column(Integer, nullable=False)
    ambiguous_matches: Mapped[int] = mapped_column(Integer, nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    match_confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    gap_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    embedding_model_version: Mapped[str] = mapped_column(String, nullable=False)
    detector_model_version: Mapped[str] = mapped_column(String, nullable=False)
    processing_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("media_id", name="uq_media_detections_media"),
        Index("ix_media_detections_school_event", "school_id", "event_id"),
        Index("ix_media_detections_school_created", "school_id", "created_at"),
    )


class MediaFrame(Base):
    """One sampled frame of a media (decisions/0021). Empty frames are recorded too."""

    __tablename__ = "media_frames"

    frame_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    media_detection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_detections.media_detection_id", ondelete="CASCADE"),
        nullable=False,
    )
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_timestamp_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    faces_detected: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "media_detection_id", "frame_index", name="uq_media_frames_media_frame"
        ),
        Index("ix_media_frames_media", "media_detection_id"),
    )


class FaceDetection(Base):
    """One detected face (decisions/0021). Includes unknowns (``outcome='unknown'``)."""

    __tablename__ = "face_detections"

    detection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    media_detection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_detections.media_detection_id", ondelete="CASCADE"),
        nullable=False,
    )
    frame_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_frames.frame_id", ondelete="CASCADE"),
        nullable=False,
    )
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_timestamp_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    face_index: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    detection_score: Mapped[float] = mapped_column(Float, nullable=False)
    landmarks: Mapped[list[list[float]] | None] = mapped_column(JSONB, nullable=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False)  # unknown|match|ambiguous

    __table_args__ = (
        UniqueConstraint(
            "media_detection_id",
            "frame_index",
            "face_index",
            name="uq_face_detections_media_frame_face",
        ),
        Index("ix_face_detections_media", "media_detection_id"),
    )


class FaceDetectionCandidate(Base):
    """One raw top-k search hit for a detected face (decisions/0021)."""

    __tablename__ = "face_detection_candidates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    detection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("face_detections.detection_id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[str] = mapped_column(String, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1-based, score desc
    cleared_threshold: Mapped[bool] = mapped_column(Boolean, nullable=False)
    emitted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        UniqueConstraint("detection_id", "rank", name="uq_fdc_detection_rank"),
        Index("ix_fdc_detection", "detection_id"),
        Index("ix_fdc_student", "student_id"),
    )
