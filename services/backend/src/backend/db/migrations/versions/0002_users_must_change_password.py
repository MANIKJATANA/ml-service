"""users.must_change_password

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-09

Adds the temp-password flag (decisions/0024). NOT NULL with a server default of
false, so existing rows backfill cleanly. This chain's bookkeeping lives in
alembic_version_backend (env.py), separate from the ML chain in the same database.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
