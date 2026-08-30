"""school_whatsapp_config

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-30

Adds the W1 per-school WhatsApp config. Mirrors backend.db.models.SchoolWhatsAppConfig.

A backend-owned, NON-SECRET, one-row-per-school settings table: ``enabled`` gates sending;
``sender_number`` is the school's own approved sender (NULL → the shared platform number is
used at send time); ``template_name`` names the approved template; ``business_name`` is a
display label. The one platform provider secret (the Gupshup API key) is a settings env var —
there is NO secret column here. ``school_id`` is the PK + a CASCADE FK; reads are by PK, so no
extra index and no CHECK.

Backend chain (alembic_version_backend). Touches only a new backend-owned table — no ML
chain, no change to existing tables. Fully reversible (the down drops the table). Verified
up→down→up on a throwaway Postgres (``wa_w1_migtest``).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "school_whatsapp_config",
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("sender_number", sa.String(), nullable=True),
        sa.Column("template_name", sa.String(), nullable=True),
        sa.Column("business_name", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # updated_at: the ORM model also declares onupdate=func.now(), which SQLAlchemy applies
        # client-side; the upsert adapter additionally sets updated_at=func.now() explicitly in
        # its on_conflict_do_update, so the column is always bumped regardless. No server-side
        # trigger is needed here.
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("school_id"),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("school_whatsapp_config")
