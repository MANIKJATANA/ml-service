"""list_pagination_indexes

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-25

Adds the composite indexes that serve BP9's server-side list pagination (decisions/0055):
each list's default sort ordered so a page is one indexed range scan of the tenant's slice
with a stable ``id`` tiebreak. Not one index per possible sort — a rarer ordering scans the
(bounded) tenant slice, which is fine at school scale. The ``name`` indexes serve the name
**sort**; the ``ILIKE '%q%'`` substring search is a leading-wildcard scan of that same
bounded slice (a B-tree can't serve it — ``pg_trgm`` GIN is the future option).

Backend chain (alembic_version_backend). Additive — indexes only, no table/column change, no
ML chain. Fully reversible (the down drops exactly what the up created). Verified up→down→up
on a throwaway Postgres.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # students: default page (created_at) + name sort/search, both scoped by school.
    op.create_index(
        "ix_students_school_created", "students", ["school_id", "created_at", "id"]
    )
    op.create_index(
        "ix_students_school_name", "students", ["school_id", "name", "id"]
    )
    # events: default page (event_date) + name sort/search.
    op.create_index(
        "ix_events_school_date", "events", ["school_id", "event_date", "id"]
    )
    op.create_index("ix_events_school_name", "events", ["school_id", "name", "id"])
    # users: staff + admin rosters page by (school, role) then created_at.
    op.create_index(
        "ix_users_school_role_created",
        "users",
        ["school_id", "role", "created_at", "id"],
    )
    # schools: the platform list's default name sort (had only the PK before).
    op.create_index("ix_schools_name", "schools", ["name", "id"])
    # media: an event's media page by created_at within the school+event slice.
    op.create_index(
        "ix_media_event_created", "media", ["school_id", "event_id", "created_at", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_media_event_created", table_name="media")
    op.drop_index("ix_schools_name", table_name="schools")
    op.drop_index("ix_users_school_role_created", table_name="users")
    op.drop_index("ix_events_school_name", table_name="events")
    op.drop_index("ix_events_school_date", table_name="events")
    op.drop_index("ix_students_school_name", table_name="students")
    op.drop_index("ix_students_school_created", table_name="students")
