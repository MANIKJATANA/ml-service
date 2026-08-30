"""student_mobile_whatsapp

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-30

Adds the Phase-0 WhatsApp contact fields (owner-locked WhatsApp direction): a nullable
``students.mobile_number`` and a NOT NULL ``students.whatsapp_opt_in`` defaulting to false.
The mobile number is optional (NULL when unknown) and loosely validated (the provider
validates authoritatively at send time); consent is never assumed — existing rows adopt
``false`` via the server default, and only an explicit opt-in flips it. No sending/provider
code lands here — this migration is purely the contact + consent columns.

Backend chain (alembic_version_backend). Additive — one nullable column + one NOT NULL column
with a server default of false (existing rows adopt false), no table/constraint change, no ML
chain. Fully reversible (the down drops exactly what the up added). Verified up->down->up on a
throwaway Postgres.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("students", sa.Column("mobile_number", sa.String(), nullable=True))
    op.add_column(
        "students",
        sa.Column(
            "whatsapp_opt_in",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("students", "whatsapp_opt_in")
    op.drop_column("students", "mobile_number")
