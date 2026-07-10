"""Service configuration (pydantic-settings) — the full v1 surface (req §12).

Everything tunable is here, never in code (NFR-8): the decision thresholds, video
FPS, ``top_k``, the ``*_impl`` adapter selectors that drive the registry/container
(NFR-1/NFR-2), and the backing-store URLs/credentials. All are ``ML_``-prefixed
env vars (e.g. ``ML_DATABASE_URL``), matching the Alembic/test conventions.

Secrets (DB password inside the DSN, ``ML_SUPABASE_KEY``) are read from the
environment and injected by the container — never committed or logged. See
``.env.example`` for the documented surface.
"""

import os
import socket

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_consumer() -> str:
    """A per-process consumer identity so replicas never share a pending list."""
    return f"worker-{socket.gethostname()}-{os.getpid()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ML_", env_file=".env", extra="ignore")

    # --- process ---------------------------------------------------------
    service_name: str = "ml-service"
    log_level: str = "INFO"

    # --- test UI (dev only, decisions/0019) ------------------------------
    # Serves a minimal browser page + /v1/test/* endpoints for hand-testing the
    # enroll + identify pipelines. Off by default; compose turns it on for local.
    enable_test_ui: bool = False

    # --- observability (Phase 4) -----------------------------------------
    log_json: bool = True  # False -> human-readable console logs for local dev
    # OTLP/HTTP trace endpoint (e.g. http://otel-collector:4318/v1/traces).
    # Empty -> tracing stays a no-op (no exporter, zero overhead).
    otel_exporter_otlp_endpoint: str = ""

    # --- decision tunables (req §12 global defaults) ---------------------
    default_match_confidence_threshold: float = 0.65
    default_gap_threshold: float = 0.08
    video_sample_fps: float = 1.0
    top_k: int = 2
    # Persist the full per-face detection audit (media_detections + children,
    # decisions/0021). Default on; turn off to skip the detection write (matches is
    # unaffected) if per-frame volume becomes a problem.
    persist_detections: bool = True

    # --- adapter selectors (name -> class via wiring/registry.py) --------
    detector_impl: str = "scrfd"
    embedder_impl: str = "arcface"
    vector_index_impl: str = "faiss"
    index_store_impl: str = "local_fs"  # local_fs (dev/volume) | supabase (prod)
    media_store_impl: str = "supabase"  # supabase (default, 0010) | local_fs (dev)
    video_extractor_impl: str = "decord"  # decord (default) | opencv (fallback)
    match_repo_impl: str = "postgres"
    detection_repo_impl: str = "postgres"
    threshold_provider_impl: str = "postgres"
    reference_photo_repo_impl: str = "postgres"
    # Reads the event roster + writes the backend's event/media status (shared DB, 0027).
    backend_event_store_impl: str = "postgres"
    queue_impl: str = "redis"  # redis (default) | inproc (single-process/dev)

    # --- model weights (buffalo_l bundle, baked into the image) ----------
    model_dir: str = "/models/buffalo_l"

    # --- backing stores --------------------------------------------------
    database_url: str = "postgresql+asyncpg://app:app@postgres:5432/app"
    db_echo: bool = False
    redis_url: str = "redis://redis:6379/0"
    # Redis socket read timeout. MUST exceed the queue's blocking-read window
    # (RedisStreamsJobQueue.block_ms, 5s): redis-py 8.x defaults socket_timeout
    # to 5s and does NOT extend it for XREADGROUP BLOCK, so a socket_timeout <=
    # the block window makes every idle poll raise TimeoutError (see decisions/0018).
    redis_socket_timeout_s: float = 30.0

    # FAISS index files (local_fs store = shared Docker volume in dev)
    index_store_dir: str = "/var/lib/ml-service/faiss"
    faiss_cache_size: int = 32

    # local_fs media store base (offline dev/CI); Supabase needs no base dir
    media_dir: str = "/var/lib/ml-service/media"

    # Supabase Storage (media + optionally the FAISS index store). The key is a
    # secret (SecretStr keeps it out of logs/reprs); empty by default so offline
    # dev with local_fs impls needs no credentials.
    supabase_url: str = ""
    supabase_key: SecretStr = SecretStr("")
    supabase_bucket: str = "media"
    # FAISS index blobs land here when index_store_impl=supabase; empty -> reuse
    # supabase_bucket (under the "faiss-indexes/" prefix).
    supabase_index_bucket: str = ""

    # --- inference queue (Redis Streams) ---------------------------------
    queue_stream: str = "inference-jobs"
    queue_group: str = "inference-workers"
    queue_consumer: str = Field(default_factory=_default_consumer)
    queue_dead_letter_stream: str = ""  # empty -> adapter derives "{stream}:dead"

    # --- readiness probe (/readyz) --------------------------------------
    readiness_timeout_s: float = 5.0


settings = Settings()
