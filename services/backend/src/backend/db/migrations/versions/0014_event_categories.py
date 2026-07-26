"""event_categories

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-26

BP11b (decisions/0059): configurable event categories + a term label + calendar filters. Adds a
tenant-owned ``event_categories`` table (mirrors ``student_groups``) and, on ``events``, a nullable
``category_id`` FK (**ON DELETE SET NULL** — removing a category un-tags its events, never deletes
them) + a nullable free-text ``term``. Seeds the 6 default categories for every existing school.

Backend chain (alembic_version_backend). Additive; no existing column changed, no ML chain.
Fully reversible (the down drops the columns/indexes then the table). Verified up->down->up on a
throwaway Postgres.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULTS = ("Sports", "Academic", "Arts", "Trip", "Ceremony", "Other")


def upgrade() -> None:
    op.create_table(
        "event_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "school_id", "name", name="uq_event_categories_school_name"
        ),
    )
    op.create_index(
        "ix_event_categories_school", "event_categories", ["school_id", "name", "id"]
    )
    op.add_column("events", sa.Column("term", sa.String(), nullable=True))
    op.add_column(
        "events",
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_events_category",
        "events",
        "event_categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_events_school_category",
        "events",
        ["school_id", "category_id", "event_date", "id"],
    )
    # Seed the 6 default categories for every existing school (one row per school × default).
    values = ", ".join(f"('{name}')" for name in _DEFAULTS)
    op.execute(
        "INSERT INTO event_categories (id, school_id, name, created_at, updated_at) "
        "SELECT gen_random_uuid(), s.id, c.name, now(), now() "
        f"FROM schools s CROSS JOIN (VALUES {values}) AS c(name)"
    )


def downgrade() -> None:
    op.drop_index("ix_events_school_category", table_name="events")
    op.drop_constraint("fk_events_category", "events", type_="foreignkey")
    op.drop_column("events", "category_id")
    op.drop_column("events", "term")
    op.drop_index("ix_event_categories_school", table_name="event_categories")
    op.drop_table("event_categories")
