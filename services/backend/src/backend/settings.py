"""Backend configuration (pydantic-settings) — the ``BE_`` env surface.

Everything tunable is here, never in code: the DB DSN, the adapter selectors that
drive the wiring registry/container, and the process/observability knobs. All are
``BE_``-prefixed env vars (e.g. ``BE_DATABASE_URL``), matching the Alembic
conventions. Secrets (the DB password inside the DSN, and — in later phases — the
JWT signing key and Supabase key) are read from the environment and never committed
or logged. The surface grows per phase as adapters land (object store, job producer,
ML client).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BE_", env_file=".env", extra="ignore")

    # --- process / observability -----------------------------------------
    service_name: str = "backend"
    log_level: str = "INFO"
    log_json: bool = True  # False -> human-readable console logs for local dev

    # --- ML service (HTTP enrollment API base URL) -----------------------
    ml_service_url: str = "http://ml-service:8000"

    # --- database (shared Postgres; backend owns its own tables + chain) --
    database_url: str = "postgresql+asyncpg://app:app@postgres:5432/app"
    db_echo: bool = False

    # --- adapter selectors (name -> class via wiring/registry.py) --------
    # The DB is Postgres-fixed (Alembic binds it); this selector exists for test
    # doubles + consistency. The object-store / job-producer / ML-client selectors
    # arrive with the phases that build those adapters (decisions/0022).
    repository_impl: str = "postgres"

    # --- readiness probe (/readyz) --------------------------------------
    readiness_timeout_s: float = 5.0


settings = Settings()
