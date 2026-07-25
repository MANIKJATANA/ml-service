"""Adapter registry — flat ``name -> "module:Class"`` tables, one per port
(mirrors the ML service's ``wiring/registry.py``).

The single source of truth mapping a ``settings.*_impl`` name to a concrete adapter
class. The container reads a selector (e.g. ``settings.repository_impl == "postgres"``),
calls :func:`resolve` to import the class, and constructs it. Adding a backend (e.g.
an S3 object store, an in-proc queue) is a one-line entry here plus a construction
branch in the container — no change to ``domain``/``services`` (decisions/0022).
"""

from __future__ import annotations

import importlib

from backend.domain.errors import ConfigurationError

SCHOOL_REPO_REGISTRY: dict[str, str] = {
    "postgres": "backend.adapters.repositories.postgres_schools:PostgresSchoolRepository",
}

USER_REPO_REGISTRY: dict[str, str] = {
    "postgres": "backend.adapters.repositories.postgres_users:PostgresUserRepository",
}

STUDENT_REPO_REGISTRY: dict[str, str] = {
    "postgres": "backend.adapters.repositories.postgres_students:PostgresStudentRepository",
}

STUDENT_GROUP_REPO_REGISTRY: dict[str, str] = {
    "postgres": (
        "backend.adapters.repositories.postgres_student_groups"
        ":PostgresStudentGroupRepository"
    ),
}

EVENT_REPO_REGISTRY: dict[str, str] = {
    "postgres": "backend.adapters.repositories.postgres_events:PostgresEventRepository",
}

MEDIA_REPO_REGISTRY: dict[str, str] = {
    "postgres": "backend.adapters.repositories.postgres_media:PostgresMediaRepository",
}

ML_RESULTS_READER_REGISTRY: dict[str, str] = {
    "postgres": "backend.adapters.repositories.ml_results:PostgresMlResultsReader",
}

NOTIFICATION_READS_REPO_REGISTRY: dict[str, str] = {
    "postgres": (
        "backend.adapters.repositories.postgres_notification_reads"
        ":PostgresNotificationReadRepository"
    ),
}

MATCH_CORRECTION_REPO_REGISTRY: dict[str, str] = {
    "postgres": (
        "backend.adapters.repositories.postgres_match_corrections"
        ":PostgresMatchCorrectionRepository"
    ),
}

DOWNLOAD_AUDIT_REPO_REGISTRY: dict[str, str] = {
    "postgres": (
        "backend.adapters.repositories.postgres_download_audit"
        ":PostgresDownloadAuditRepository"
    ),
}

EVENT_JOB_PRODUCER_REGISTRY: dict[str, str] = {
    "redis": "backend.adapters.queue.redis_producer:RedisEventJobProducer",
    "inproc": "backend.adapters.queue.inproc_producer:InProcEventJobProducer",
}

OBJECT_STORE_REGISTRY: dict[str, str] = {
    "supabase": "backend.adapters.object_store.supabase_store:SupabaseObjectStore",
    "local_fs": "backend.adapters.object_store.local_fs_store:LocalFsObjectStore",
}

ML_ENROLLMENT_CLIENT_REGISTRY: dict[str, str] = {
    "http": "backend.adapters.ml_client.http_enrollment:HttpMlEnrollmentClient",
    "fake": "backend.adapters.ml_client.fake_enrollment:FakeMlEnrollmentClient",
}

THUMBNAILER_REGISTRY: dict[str, str] = {
    "pillow": "backend.adapters.imaging.pillow_thumbnailer:PillowThumbnailer",
}

# Notification channels (BP4). Unlike the single-selector ports above, the container
# resolves a LIST of these from the comma-separated ``BE_NOTIFICATION_CHANNELS`` and wraps
# them in a CompositeNotifier — so channels run together or one at a time. email/whatsapp
# are future one-line additions here + a construction branch.
NOTIFICATION_CHANNEL_REGISTRY: dict[str, str] = {
    "log": "backend.adapters.notification.log_channel:LogNotificationChannel",
}

RATE_LIMITER_REGISTRY: dict[str, str] = {
    "memory": "backend.adapters.rate_limit.memory:InMemoryRateLimiter",
    "redis": "backend.adapters.rate_limit.redis_limiter:RedisRateLimiter",
}

PASSWORD_HASHER_REGISTRY: dict[str, str] = {
    "argon2": "backend.adapters.security.argon2_hasher:Argon2PasswordHasher",
}

TOKEN_SERVICE_REGISTRY: dict[str, str] = {
    "jwt": "backend.adapters.security.jwt_tokens:JwtTokenService",
}

PERMISSION_RESOLVER_REGISTRY: dict[str, str] = {
    "static": "backend.adapters.security.static_permissions:StaticPermissionResolver",
}


def resolve(registry: dict[str, str], name: str) -> type:
    """Look ``name`` up in ``registry`` and import the referenced class.

    Raises :class:`ConfigurationError` for an unknown name or an unimportable /
    malformed target, so a misconfigured ``*_impl`` fails loud at wiring time.
    """
    target = registry.get(name)
    if target is None:
        raise ConfigurationError(
            f"unknown adapter impl {name!r}; known: {sorted(registry)}"
        )
    module_path, _, class_name = target.partition(":")
    if not class_name:
        raise ConfigurationError(
            f"malformed registry target {target!r} (need module:Class)"
        )
    try:
        module = importlib.import_module(module_path)
        return getattr(module, class_name)  # type: ignore[no-any-return]
    except (ImportError, AttributeError) as exc:
        raise ConfigurationError(f"cannot import {target!r}: {exc}") from exc
