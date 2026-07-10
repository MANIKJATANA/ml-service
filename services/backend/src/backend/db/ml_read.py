"""Read-only mapping of ML-owned result tables (decisions/0028).

The single point where the backend knows the shape of the ML service's result schema.
This is a SQLAlchemy Core ``Table`` on a **separate** ``MetaData()`` — deliberately NOT
the backend ``Base.metadata`` — so the backend Alembic chain never manages, migrates, or
drops it. The ML service owns and writes ``matches`` (decisions/0012, 0021); the backend
only **reads** it, tenant-scoped by ``school_id``, via ``PostgresMlResultsReader``.

Only the columns the backend consumes are declared. A Phase-7 ``information_schema``
contract test asserts these still exist in the live DB, so an ML migration that
drops/renames one fails backend CI loudly rather than at runtime.
"""

from __future__ import annotations

import sqlalchemy as sa

# Isolated from Base.metadata on purpose (see module docstring). Its ``create_all`` is
# used only by the reader's gated integration test to stand up a matching table.
ml_read_metadata = sa.MetaData()

# ML-owned ``matches``: one row per (media_id, student_id) — the deduped "who appears in
# this media" answer. Indexed (school_id, event_id) and (school_id, student_id) on the ML
# side (decisions/0012). All join keys are stored as strings (canonical UUID strings —
# decisions/0022), so reads compare against the backend's string ids directly.
matches = sa.Table(
    "matches",
    ml_read_metadata,
    sa.Column("match_id", sa.Uuid(), primary_key=True),
    sa.Column("school_id", sa.String(), nullable=False),
    sa.Column("event_id", sa.String(), nullable=False),
    sa.Column("student_id", sa.String(), nullable=False),
    sa.Column("media_id", sa.String(), nullable=False),
    sa.Column("confidence_score", sa.Float(), nullable=False),
    sa.Column("needs_review", sa.Boolean(), nullable=False),
)
