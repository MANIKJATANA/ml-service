"""per-face detection audit + matches.frames_matched + appearances view

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-07

decisions/0021. Media-centric detection evidence
(media_detections -> media_frames -> face_detections -> face_detection_candidates,
replace-by-media, FK ON DELETE CASCADE) plus the student-centric
``student_media_appearances`` view; ``matches`` gains ``frames_matched``.
Mirrors ml_service.db.models.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPEARANCES_VIEW = "student_media_appearances"

_CREATE_APPEARANCES_VIEW = f"""
CREATE VIEW {_APPEARANCES_VIEW} AS
SELECT md.school_id,
       md.event_id,
       c.student_id,
       md.media_id,
       fd.frame_index,
       fd.frame_timestamp_ms,
       fd.bbox,
       c.score,
       c.needs_review
FROM face_detection_candidates c
JOIN face_detections fd ON fd.detection_id = c.detection_id
JOIN media_detections md ON md.media_detection_id = fd.media_detection_id
WHERE c.emitted IS TRUE
"""


def upgrade() -> None:
    # matches gains frames_matched; backfill existing rows to 1, then drop the
    # server default so the app supplies it explicitly (like the other columns).
    op.add_column(
        "matches",
        sa.Column("frames_matched", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column("matches", "frames_matched", server_default=None)

    op.create_table(
        "media_detections",
        sa.Column("media_detection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_id", sa.String(), nullable=False),
        sa.Column("school_id", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("media_uri", sa.String(), nullable=False),
        sa.Column("video_fps", sa.Float(), nullable=True),
        sa.Column("frames_sampled", sa.Integer(), nullable=False),
        sa.Column("faces_detected", sa.Integer(), nullable=False),
        sa.Column("candidates_above_threshold", sa.Integer(), nullable=False),
        sa.Column("unknown_faces", sa.Integer(), nullable=False),
        sa.Column("matches_emitted", sa.Integer(), nullable=False),
        sa.Column("ambiguous_matches", sa.Integer(), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("match_confidence_threshold", sa.Float(), nullable=False),
        sa.Column("gap_threshold", sa.Float(), nullable=False),
        sa.Column("embedding_model_version", sa.String(), nullable=False),
        sa.Column("detector_model_version", sa.String(), nullable=False),
        sa.Column("processing_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("media_detection_id"),
        sa.UniqueConstraint("media_id", name="uq_media_detections_media"),
    )
    op.create_index(
        "ix_media_detections_school_event", "media_detections", ["school_id", "event_id"]
    )
    op.create_index(
        "ix_media_detections_school_created",
        "media_detections",
        ["school_id", "created_at"],
    )

    op.create_table(
        "media_frames",
        sa.Column("frame_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_detection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column("frame_timestamp_ms", sa.Integer(), nullable=True),
        sa.Column("faces_detected", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("frame_id"),
        sa.ForeignKeyConstraint(
            ["media_detection_id"],
            ["media_detections.media_detection_id"],
            name="fk_media_frames_media",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "media_detection_id", "frame_index", name="uq_media_frames_media_frame"
        ),
    )
    op.create_index("ix_media_frames_media", "media_frames", ["media_detection_id"])

    op.create_table(
        "face_detections",
        sa.Column("detection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_detection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("frame_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column("frame_timestamp_ms", sa.Integer(), nullable=True),
        sa.Column("face_index", sa.Integer(), nullable=False),
        sa.Column("bbox", postgresql.JSONB(), nullable=False),
        sa.Column("detection_score", sa.Float(), nullable=False),
        sa.Column("landmarks", postgresql.JSONB(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("detection_id"),
        sa.ForeignKeyConstraint(
            ["media_detection_id"],
            ["media_detections.media_detection_id"],
            name="fk_face_detections_media",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["frame_id"],
            ["media_frames.frame_id"],
            name="fk_face_detections_frame",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "media_detection_id",
            "frame_index",
            "face_index",
            name="uq_face_detections_media_frame_face",
        ),
    )
    op.create_index("ix_face_detections_media", "face_detections", ["media_detection_id"])

    op.create_table(
        "face_detection_candidates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("detection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("cleared_threshold", sa.Boolean(), nullable=False),
        sa.Column("emitted", sa.Boolean(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["detection_id"],
            ["face_detections.detection_id"],
            name="fk_fdc_detection",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("detection_id", "rank", name="uq_fdc_detection_rank"),
    )
    op.create_index("ix_fdc_detection", "face_detection_candidates", ["detection_id"])
    op.create_index("ix_fdc_student", "face_detection_candidates", ["student_id"])

    op.execute(_CREATE_APPEARANCES_VIEW)


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {_APPEARANCES_VIEW}")
    op.drop_index("ix_fdc_student", table_name="face_detection_candidates")
    op.drop_index("ix_fdc_detection", table_name="face_detection_candidates")
    op.drop_table("face_detection_candidates")
    op.drop_index("ix_face_detections_media", table_name="face_detections")
    op.drop_table("face_detections")
    op.drop_index("ix_media_frames_media", table_name="media_frames")
    op.drop_table("media_frames")
    op.drop_index("ix_media_detections_school_created", table_name="media_detections")
    op.drop_index("ix_media_detections_school_event", table_name="media_detections")
    op.drop_table("media_detections")
    op.drop_column("matches", "frames_matched")
