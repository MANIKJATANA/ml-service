"""ORM models for the ML-service metadata DB (requirements §10).

These mirror the Alembic ``0001_initial`` migration exactly. Application code
never issues DDL — it assumes the schema a migration already established
(decisions/0007). Columns follow the req §10 data contracts.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
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
