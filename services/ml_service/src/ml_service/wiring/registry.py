"""Adapter registry — flat ``name -> "module:Class"`` tables, one per port
(architecture §8.1).

This is the single source of truth mapping a ``settings.*_impl`` name to a
concrete adapter class. The container reads a selector (e.g. ``settings.
detector_impl == "scrfd"``), calls :func:`resolve` to import the class, and
instantiates it with the impl-appropriate config. Adding a new backend (S3
media, Milvus index, SQS queue) is a one-line entry here plus a construction
branch in the container — no change to ``domain``/``orchestration`` (NFR-1/NFR-2).

Values are dotted ``package.module:ClassName`` strings so importing a Linux-only
adapter (insightface/decord) is deferred until it is actually selected — keeping
Windows dev importable.
"""

from __future__ import annotations

import importlib

from ml_service.domain.errors import ConfigurationError

DETECTOR_REGISTRY: dict[str, str] = {
    "scrfd": "ml_service.adapters.detectors.scrfd_insightface:SCRFDDetector",
}

EMBEDDER_REGISTRY: dict[str, str] = {
    "arcface": "ml_service.adapters.embedders.arcface_insightface:ArcFaceEmbedder",
}

VECTOR_INDEX_REGISTRY: dict[str, str] = {
    "faiss": "ml_service.adapters.vector_index.faiss_per_school:FaissPerSchoolVectorIndex",
}

INDEX_STORE_REGISTRY: dict[str, str] = {
    "local_fs": "ml_service.adapters.vector_index._index_store:LocalFsIndexStore",
    "supabase": "ml_service.adapters.vector_index._index_store:SupabaseIndexStore",
}

# Per-school enrollment write lock (decisions/0052): in-process (Option A, single-replica)
# or Redis (Option B, multi-replica). See wiring/container.py::write_lock_provider.
FAISS_LOCK_REGISTRY: dict[str, str] = {
    "inproc": "ml_service.adapters.vector_index._locks:InProcLockProvider",
    "redis": "ml_service.adapters.vector_index._redis_locks:RedisLockProvider",
}

MEDIA_STORE_REGISTRY: dict[str, str] = {
    "local_fs": "ml_service.adapters.media_store.local_fs:LocalFsMediaStore",
    "supabase": "ml_service.adapters.media_store.supabase_storage:SupabaseMediaStore",
}

VIDEO_EXTRACTOR_REGISTRY: dict[str, str] = {
    "decord": "ml_service.adapters.video.decord_extractor:DecordFrameExtractor",
    "opencv": "ml_service.adapters.video.opencv_extractor:OpenCvFrameExtractor",
}

MATCH_REPO_REGISTRY: dict[str, str] = {
    "postgres": "ml_service.adapters.repository.postgres_matches:PostgresMatchRepository",
}

DETECTION_REPO_REGISTRY: dict[str, str] = {
    "postgres": (
        "ml_service.adapters.repository.postgres_detections"
        ":PostgresDetectionRepository"
    ),
}

THRESHOLD_PROVIDER_REGISTRY: dict[str, str] = {
    "postgres": "ml_service.adapters.repository.postgres_thresholds:PostgresThresholdProvider",
}

REFERENCE_PHOTO_REPO_REGISTRY: dict[str, str] = {
    "postgres": (
        "ml_service.adapters.repository.postgres_reference_photos"
        ":PostgresReferencePhotoRepository"
    ),
}

BACKEND_EVENT_STORE_REGISTRY: dict[str, str] = {
    "postgres": "ml_service.adapters.repository.backend_store:PostgresBackendEventStore",
}

QUEUE_REGISTRY: dict[str, str] = {
    "redis": "ml_service.adapters.queue.redis_streams:RedisStreamsJobQueue",
    "inproc": "ml_service.adapters.queue.inproc_queue:InProcJobQueue",
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
        raise ConfigurationError(f"malformed registry target {target!r} (need module:Class)")
    try:
        module = importlib.import_module(module_path)
        return getattr(module, class_name)  # type: ignore[no-any-return]
    except (ImportError, AttributeError) as exc:
        raise ConfigurationError(f"cannot import {target!r}: {exc}") from exc
