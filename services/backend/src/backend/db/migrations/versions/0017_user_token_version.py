"""user_token_version

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-09

Adds ``users.token_version`` (BP18d, decisions/0068): a per-account counter bumped on every
password change/reset. Each JWT carries the issuing user's version as a ``tv`` claim; the
backend compares it to this column on every request (``get_current_user``) and on refresh, so a
changed/reset password immediately invalidates all previously-issued tokens ("log out
everywhere"). A transparent rehash-on-login does NOT bump it.

Backend chain (alembic_version_backend). Additive — one NOT NULL column with a server default of
0 (existing rows adopt 0), no table/constraint change, no ML chain. Fully reversible (the down
drops exactly what the up added).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
