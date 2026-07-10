"""Backend DB layer: declarative base, ORM models, engine/session, migrations.

Backend-owned tables only. Job status lives on these tables (the ML worker writes the
``events``/``media`` status columns directly — decisions/0027), so no ML-schema read is
needed for it. Gallery *contents* (who appears in what) ARE read from the ML-owned
``matches`` table via ``ml_read.py`` (decisions/0028) — read-only SQLAlchemy Core tables
on their own ``MetaData``, deliberately kept out of ``Base.metadata`` so the backend
Alembic chain never manages them.
"""
