"""Backend DB layer: declarative base, ORM models, engine/session, migrations.

Backend-owned tables only. Job status lives on these tables (the ML worker writes the
``events``/``media`` status columns directly — decisions/0027), so no ML-schema read is
needed here in Phase 5. Phase 6 adds ``ml_read.py`` for gallery *contents* (matches /
appearances) as read-only Core tables, deliberately kept out of ``Base.metadata`` so the
backend Alembic chain never manages them.
"""
