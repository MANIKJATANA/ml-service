"""Adapters — concrete implementations of the domain ports.

The only layer (with ``api``/``wiring``/``workers``) allowed to import concrete IO
libraries (SQLAlchemy, httpx, redis, supabase). Selected by config via
``wiring/registry.py`` (decisions/0022).
"""
