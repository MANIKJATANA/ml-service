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
    # CORS allow-list for browser callers (the FE), comma-separated. Empty -> the
    # CORS middleware is not installed (nothing changes for non-browser callers).
    # Must be explicit origins: "*" is rejected at startup (a credentialed wildcard
    # would let any origin read authenticated responses).
    cors_origins: str = ""

    # --- ML service (HTTP enrollment API) --------------------------------
    ml_service_url: str = "http://ml-service:8000"
    # enroll fetches+detects+embeds; the ML service loads buffalo_l lazily on its FIRST
    # request (SCRFD+ArcFace + ONNX CPU init), which can take tens of seconds cold — so
    # allow a full minute to avoid a ReadTimeout on a fresh ML container.
    ml_http_timeout_s: float = 60.0

    # --- event-job producer (ML inference enqueue, decisions/0027) --------
    # redis XADDs one event job to the shared stream the ML worker consumes; inproc
    # records jobs in-memory for offline dev (pair with object_store_impl=local_fs).
    event_job_producer_impl: str = "redis"
    redis_url: str = "redis://redis:6379/0"  # the shared Redis (matches ML's default)
    # Must equal ML_QUEUE_STREAM — the field/stream contract is verified against ML
    # code (decisions/0022); a mismatch means the worker never sees the jobs.
    queue_stream: str = "inference-jobs"
    event_media_prefix: str = "events"  # object-key prefix; distinct from reference-photos

    # --- object store (reference-photo signed upload URLs, decisions/0026) -
    # supabase mints direct-to-Supabase upload URLs; local_fs is a credential-free
    # dev stub (pair with ml_enrollment_client_impl=fake to run without either).
    object_store_impl: str = "supabase"
    ml_enrollment_client_impl: str = "http"
    supabase_url: str = ""  # e.g. https://<project-ref>.supabase.co
    supabase_key: SecretStr = SecretStr("")  # SECRET: service/access key
    # Must equal ML_SUPABASE_BUCKET — the backend uploads where ML reads (0022).
    supabase_bucket: str = "media"
    reference_photo_prefix: str = "reference-photos"  # object-key prefix (0022)
    max_upload_mb: int = 30  # advertised to the FE; enforced client-side in v1
    object_store_dir: str = "/var/lib/backend/objects"  # local_fs dev target

    # --- image thumbnails (BP17, decisions/0056) -------------------------
    # The backend downscales each uploaded image to a small JPEG preview (tiles + avatars);
    # the lightbox/download stay full-res. Pillow lives behind the Thumbnailer adapter.
    thumbnailer_impl: str = "pillow"
    image_thumbnail_max_edge: int = 512  # longest-edge cap (px)
    image_thumbnail_quality: int = 70  # JPEG quality (1-95)

    # --- galleries / download (decisions/0028) ---------------------------
    # TTL of the short-lived signed download URLs the galleries mint on demand.
    download_url_ttl_s: int = 3600  # 1 hour

    # --- list pagination (BP9, decisions/0055) ---------------------------
    # Server-side pagination on every list/gallery endpoint. default = the page size the FE
    # requests; max = the hard ceiling the Query(le=) enforces (a bigger ?limit= 422s).
    default_page_size: int = 50
    max_page_size: int = 200

    # --- notifications (BP4, decisions/0041) -----------------------------
    # Outbound channels the "Notify students" action fans out to, comma-separated (like
    # cors_origins). Resolved per-name via NOTIFICATION_CHANNEL_REGISTRY and wrapped in a
    # CompositeNotifier, so they run together or one at a time. Default "log" (structured,
    # PII-free). Empty -> a no-op notifier (outbound disabled; the in-app signal is
    # unaffected). email/whatsapp are future channels — add the adapter + a registry entry.
    notification_channels: str = "log"

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

    # --- rate limiting (BP8c, decisions/0051) ----------------------------
    # A fixed-window request throttle, keyed by a global bucket + a per-school (tenant)
    # bucket (school_id derived from the JWT) + a stricter bucket on /v1/auth/* (brute-force
    # guard). memory = per-replica counters; redis = cross-replica (reuses redis_url).
    # Fail-open: a store outage never blocks requests. Disabled -> the middleware is not
    # installed. The backend sits behind the Next BFF (no real client IP), so there is no
    # per-IP tier — per-IP limiting belongs at the edge/ingress (documented).
    rate_limit_enabled: bool = True
    rate_limit_impl: str = "memory"  # memory | redis
    rate_limit_window_s: int = 60
    rate_limit_global_per_min: int = 6000  # all requests, this replica
    rate_limit_school_per_min: int = 600  # per tenant (school_id from the token)
    # Stricter, on /v1/auth/*. This is a SINGLE bucket shared across all schools (no client
    # IP behind the BFF), so keep it generous enough not to lock out legitimate concurrent
    # logins/refreshes — it's a coarse brute-force ceiling, not per-attacker (per-IP belongs
    # at the ingress). Tune per deployment.
    rate_limit_auth_per_min: int = 300

    # --- security headers (BP8c, decisions/0051) -------------------------
    # Defense-in-depth headers on every API response (the browser-facing set lives in the
    # FE next.config, since only the Next BFF talks to the browser). HSTS is off by default
    # (dev is http); enable it behind TLS in prod.
    security_headers_enabled: bool = True
    hsts_enabled: bool = False
    hsts_max_age_s: int = 63072000  # 2 years


settings = Settings()
