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

from pydantic import SecretStr
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

    # --- auth / JWT (decisions/0024) -------------------------------------
    # Empty default is intentional: NOT a hardcoded secret. Building the JWT token
    # service with an empty key raises ConfigurationError, so a prod deploy fails
    # loud without BE_JWT_SECRET while imports/tests that never mint tokens stay green.
    jwt_secret: SecretStr = SecretStr("")  # HS256: use >= 32 bytes (RFC 7518 §3.2)
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "backend"
    access_token_ttl_s: int = 900  # 15 minutes
    refresh_token_ttl_s: int = 1_209_600  # 14 days

    # --- adapter selectors (name -> class via wiring/registry.py) --------
    # The DB is Postgres-fixed (Alembic binds it); this selector exists for test
    # doubles + consistency. The object-store / job-producer / ML-client selectors
    # arrive with the phases that build those adapters (decisions/0022).
    repository_impl: str = "postgres"
    password_hasher_impl: str = "argon2"
    token_service_impl: str = "jwt"
    permission_resolver_impl: str = "static"

    # --- readiness probe (/readyz) --------------------------------------
    readiness_timeout_s: float = 5.0


settings = Settings()
