"""Composition root — builds concrete adapters from settings and injects them
into the orchestration services (architecture §8.1).

This is one of the few layers allowed to import adapters. It reads each
``settings.*_impl`` selector, resolves the class via :mod:`wiring.registry`, and
constructs it with the impl-appropriate config. Adapters are built once and
memoized: the detector/embedder models load a single time, and the FAISS
per-school cache and DB engine are shared across the enrollment and inference
services. Nothing is built until first requested, so an API pod that only serves
enrollment never constructs the queue, and a worker never constructs the
reference-photo repo.

Secrets (DB password, Supabase key) come from ``settings`` (i.e. the
environment) and are never stored in code.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ml_service.adapters.repository._engine import make_engine, make_sessionmaker
from ml_service.domain.errors import ConfigurationError
from ml_service.domain.ports import (
    DetectionRepository,
    FaceDetector,
    FaceEmbedder,
    JobQueue,
    MatchRepository,
    MediaStore,
    ReferencePhotoRepository,
    ThresholdProvider,
    VectorIndex,
    VideoFrameExtractor,
)
from ml_service.orchestration.enrollment import EnrollmentService
from ml_service.orchestration.inference import InferenceService
from ml_service.wiring import registry
from ml_service.wiring.settings import Settings

if TYPE_CHECKING:
    from redis.asyncio import Redis


class Container:
    """Lazily builds and memoizes adapters + services from ``Settings``."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        # Builds run in threadpool workers (models load off the event loop), and
        # FastAPI resolves cold concurrent requests in parallel — so serialize
        # the lazy builders to avoid double-loading models / building two FAISS
        # caches. Reentrant: a service build re-enters via its adapter getters.
        self._lock = threading.RLock()
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None
        self._redis: Redis | None = None
        self._detector: FaceDetector | None = None
        self._embedder: FaceEmbedder | None = None
        self._index: VectorIndex | None = None
        self._media_store: MediaStore | None = None
        self._extractor: VideoFrameExtractor | None = None
        self._match_repo: MatchRepository | None = None
        self._detection_repo: DetectionRepository | None = None
        self._threshold_provider: ThresholdProvider | None = None
        self._reference_photos: ReferencePhotoRepository | None = None
        self._queue: JobQueue | None = None
        self._enrollment: EnrollmentService | None = None
        self._inference: InferenceService | None = None

    # ---- shared resources ----------------------------------------------

    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        if self._sessionmaker is None:
            with self._lock:
                if self._sessionmaker is None:
                    self._engine = make_engine(self._s.database_url, echo=self._s.db_echo)
                    self._sessionmaker = make_sessionmaker(self._engine)
        return self._sessionmaker

    def redis(self) -> Redis:
        if self._redis is None:
            from redis.asyncio import Redis

            with self._lock:
                if self._redis is None:
                    # socket_timeout must exceed the queue's XREADGROUP BLOCK
                    # window; redis-py 8.x's 5s default collides with block_ms=5s
                    # and raises TimeoutError on every idle poll (decisions/0018).
                    self._redis = Redis.from_url(
                        self._s.redis_url,
                        socket_timeout=self._s.redis_socket_timeout_s,
                        socket_keepalive=True,
                    )
        return self._redis

    # ---- adapters (one memoized instance each) -------------------------

    def detector(self) -> FaceDetector:
        if self._detector is None:
            with self._lock:
                if self._detector is None:
                    cls = registry.resolve(registry.DETECTOR_REGISTRY, self._s.detector_impl)
                    self._detector = cls(model_dir=self._s.model_dir)
        return self._detector

    def embedder(self) -> FaceEmbedder:
        if self._embedder is None:
            with self._lock:
                if self._embedder is None:
                    cls = registry.resolve(registry.EMBEDDER_REGISTRY, self._s.embedder_impl)
                    self._embedder = cls(model_dir=self._s.model_dir)
        return self._embedder

    def _index_store(self) -> object:
        impl = self._s.index_store_impl
        cls = registry.resolve(registry.INDEX_STORE_REGISTRY, impl)
        if impl == "local_fs":
            return cls(self._s.index_store_dir)
        if impl == "supabase":
            return cls(
                self._s.supabase_url,
                self._s.supabase_key.get_secret_value(),
                self._s.supabase_index_bucket or self._s.supabase_bucket,
            )
        raise ConfigurationError(f"no construction wiring for index_store_impl {impl!r}")

    def vector_index(self) -> VectorIndex:
        if self._index is None:
            with self._lock:
                if self._index is None:
                    cls = registry.resolve(
                        registry.VECTOR_INDEX_REGISTRY, self._s.vector_index_impl
                    )
                    # Embedder version binds the index (fail-loud on mismatch, §7.3).
                    self._index = cls(
                        store=self._index_store(),
                        embedder_version=self.embedder().version,
                        cache_size=self._s.faiss_cache_size,
                    )
        return self._index

    def media_store(self) -> MediaStore:
        if self._media_store is None:
            with self._lock:
                if self._media_store is None:
                    impl = self._s.media_store_impl
                    cls = registry.resolve(registry.MEDIA_STORE_REGISTRY, impl)
                    if impl == "local_fs":
                        self._media_store = cls(self._s.media_dir)
                    elif impl == "supabase":
                        self._media_store = cls(
                            self._s.supabase_url,
                            self._s.supabase_key.get_secret_value(),
                            self._s.supabase_bucket,
                        )
                    else:
                        raise ConfigurationError(
                            f"no construction wiring for media_store_impl {impl!r}"
                        )
        return self._media_store

    def extractor(self) -> VideoFrameExtractor:
        if self._extractor is None:
            with self._lock:
                if self._extractor is None:
                    cls = registry.resolve(
                        registry.VIDEO_EXTRACTOR_REGISTRY, self._s.video_extractor_impl
                    )
                    self._extractor = cls()
        return self._extractor

    def match_repo(self) -> MatchRepository:
        if self._match_repo is None:
            with self._lock:
                if self._match_repo is None:
                    cls = registry.resolve(
                        registry.MATCH_REPO_REGISTRY, self._s.match_repo_impl
                    )
                    self._match_repo = cls(self.sessionmaker())
        return self._match_repo

    def detection_repo(self) -> DetectionRepository:
        if self._detection_repo is None:
            with self._lock:
                if self._detection_repo is None:
                    cls = registry.resolve(
                        registry.DETECTION_REPO_REGISTRY, self._s.detection_repo_impl
                    )
                    self._detection_repo = cls(self.sessionmaker())
        return self._detection_repo

    def threshold_provider(self) -> ThresholdProvider:
        if self._threshold_provider is None:
            with self._lock:
                if self._threshold_provider is None:
                    cls = registry.resolve(
                        registry.THRESHOLD_PROVIDER_REGISTRY,
                        self._s.threshold_provider_impl,
                    )
                    self._threshold_provider = cls(
                        self.sessionmaker(),
                        default_match_confidence=self._s.default_match_confidence_threshold,
                        default_gap=self._s.default_gap_threshold,
                    )
        return self._threshold_provider

    def reference_photos(self) -> ReferencePhotoRepository:
        if self._reference_photos is None:
            with self._lock:
                if self._reference_photos is None:
                    cls = registry.resolve(
                        registry.REFERENCE_PHOTO_REPO_REGISTRY,
                        self._s.reference_photo_repo_impl,
                    )
                    self._reference_photos = cls(self.sessionmaker())
        return self._reference_photos

    def job_queue(self) -> JobQueue:
        if self._queue is None:
            with self._lock:
                if self._queue is None:
                    impl = self._s.queue_impl
                    cls = registry.resolve(registry.QUEUE_REGISTRY, impl)
                    if impl == "redis":
                        self._queue = cls(
                            self.redis(),
                            stream=self._s.queue_stream,
                            group=self._s.queue_group,
                            consumer=self._s.queue_consumer,
                            dead_letter_stream=self._s.queue_dead_letter_stream or None,
                        )
                    elif impl == "inproc":
                        self._queue = cls()
                    else:
                        raise ConfigurationError(
                            f"no construction wiring for queue_impl {impl!r}"
                        )
        return self._queue

    # ---- services ------------------------------------------------------

    def enrollment_service(self) -> EnrollmentService:
        if self._enrollment is None:
            with self._lock:
                if self._enrollment is None:
                    self._enrollment = EnrollmentService(
                        reference_photos=self.reference_photos(),
                        media_store=self.media_store(),
                        detector=self.detector(),
                        embedder=self.embedder(),
                        index=self.vector_index(),
                    )
        return self._enrollment

    def inference_service(self) -> InferenceService:
        if self._inference is None:
            with self._lock:
                if self._inference is None:
                    self._inference = InferenceService(
                        media_store=self.media_store(),
                        extractor=self.extractor(),
                        detector=self.detector(),
                        embedder=self.embedder(),
                        index=self.vector_index(),
                        repo=self.match_repo(),
                        thresholds=self.threshold_provider(),
                        detection_repo=self.detection_repo(),
                        top_k=self._s.top_k,
                        video_fps=self._s.video_sample_fps,
                        persist_detections=self._s.persist_detections,
                    )
        return self._inference

    # ---- lifecycle -----------------------------------------------------

    async def check_readiness(self) -> dict[str, bool]:
        """Best-effort probe of the configured infra deps for ``/readyz``.

        Only pings what this deployment actually uses (Postgres when a postgres
        repo is selected; Redis when the redis queue is selected). Returns a
        per-dependency ok/not-ok map; an empty map means nothing to check.
        """
        from sqlalchemy import text

        checks: dict[str, bool] = {}
        uses_postgres = "postgres" in (
            self._s.match_repo_impl,
            self._s.detection_repo_impl,
            self._s.threshold_provider_impl,
            self._s.reference_photo_repo_impl,
        )
        timeout = self._s.readiness_timeout_s
        if uses_postgres:
            try:
                async with asyncio.timeout(timeout):
                    async with self.sessionmaker()() as session:
                        await session.execute(text("SELECT 1"))
                checks["database"] = True
            except Exception:  # unreachable/slow/down -> not ready (bounded)
                checks["database"] = False
        if self._s.queue_impl == "redis":
            try:
                async with asyncio.timeout(timeout):
                    checks["redis"] = bool(await self.redis().ping())
            except Exception:
                checks["redis"] = False
        return checks

    async def aclose(self) -> None:
        """Dispose shared resources. Safe to call once at shutdown."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sessionmaker = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
