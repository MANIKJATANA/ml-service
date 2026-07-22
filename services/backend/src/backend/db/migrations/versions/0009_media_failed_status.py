"""media.processing_status add 'failed'

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-16

BP8a — a permanently-bad photo used to look ``pending`` forever; now the ML worker marks
one it can't process ``failed`` (visible + retryable via a redistribute). Widens the
``ck_media_processing_status`` CHECK from ``('pending','completed')`` to add ``'failed'``.
Mirrors ``backend.db.models.Media`` + the ``MediaProcessingStatus`` domain enum.

Reversible **only while no row is ``'failed'``** — the downgrade re-imposes the 2-value
CHECK, which fails if any failed photo exists. Backend chain (alembic_version_backend);
touches only the backend-owned ``media`` table (the ML worker writes the value directly,
so this must be applied before deploying the worker change).
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CK = "ck_media_processing_status"


def upgrade() -> None:
    op.drop_constraint(_CK, "media", type_="check")
    op.create_check_constraint(
        _CK, "media", "processing_status IN ('pending', 'completed', 'failed')"
    )


def downgrade() -> None:
    op.drop_constraint(_CK, "media", type_="check")
    op.create_check_constraint(
        _CK, "media", "processing_status IN ('pending', 'completed')"
    )
