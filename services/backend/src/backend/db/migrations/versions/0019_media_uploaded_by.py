"""media.uploaded_by

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-28

BP23 (decisions/0078) — attribution: media had no uploader column, so "who uploaded this
photo" was unrecoverable. Adds a nullable ``media.uploaded_by`` UUID FK → ``users.id`` with
**ON DELETE SET NULL** (a row outlives its uploader's account), stamped at register from the
route actor. Mirrors ``events.created_by``'s FK pattern (0004/models).

Backend chain (alembic_version_backend). Additive — one nullable column + its FK, no existing
column changed, no index (display-only), no ML chain. **No backfill** — pre-BP23 photos keep a
null uploader (the history that was never recorded can't be recovered; forward-looking from
launch). Fully reversible (the down drops the FK then the column). Verified up→down→up on a
throwaway Postgres.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "media",
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_media_uploaded_by",
        "media",
        "users",
        ["uploaded_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_media_uploaded_by", "media", type_="foreignkey")
    op.drop_column("media", "uploaded_by")
