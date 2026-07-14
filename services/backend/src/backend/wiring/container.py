"""Composition root — builds concrete adapters from settings and injects them
(mirrors the ML service's ``wiring/container.py``).

One of the few layers allowed to import adapters. It reads each ``settings.*_impl``
selector, resolves the class via :mod:`wiring.registry`, and constructs it. Adapters
are built once and memoized: the DB engine/sessionmaker is shared across repositories.
Nothing is built until first requested. Secrets (the DB password in the DSN) come
from ``settings`` (the environment) and are never stored in code.

The surface grows per phase; Phase 5 adds the event + media repositories, the event-job
producer, and the event/media services (0027). Job status lives on the backend's own
event/media rows (the ML worker writes them), so there's no results-reader or poller.
"""

from __future__ import annotations

import asyncio
import threading

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backend.adapters.notification.composite import CompositeNotifier
from backend.db.session import make_engine, make_sessionmaker
from backend.domain.ports import (
    EventJobProducer,
    EventRepository,
    MatchCorrectionRepository,
    MediaRepository,
    MlEnrollmentClient,
    MlResultsReader,
    NotificationChannel,
    NotificationReadRepository,
    ObjectStore,
    PasswordHasher,
    PermissionResolver,
    SchoolRepository,
    StudentRepository,
    TokenService,
    UserRepository,
)
from backend.services.auth_service import AuthService
from backend.services.dashboard_service import DashboardService
from backend.services.event_service import EventService
from backend.services.gallery_service import GalleryService
from backend.services.listing_service import ListingService
from backend.services.media_service import MediaService
from backend.services.notification_service import NotificationService
from backend.services.onboarding_service import OnboardingService
from backend.services.review_service import ReviewService
from backend.services.student_service import StudentService
from backend.settings import Settings
from backend.wiring import registry


class Container:
    """Lazily builds and memoizes adapters from ``Settings``."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        # FastAPI resolves cold concurrent requests in parallel; serialize the lazy
        # builders so a resource is constructed once. Reentrant on purpose.
        self._lock = threading.RLock()
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None
        self._school_repo: SchoolRepository | None = None
        self._user_repo: UserRepository | None = None
        self._student_repo: StudentRepository | None = None
        self._event_repo: EventRepository | None = None
        self._media_repo: MediaRepository | None = None
        self._ml_results_reader: MlResultsReader | None = None
        self._match_correction_repo: MatchCorrectionRepository | None = None
        self._notification_reads_repo: NotificationReadRepository | None = None
        self._notifier: NotificationChannel | None = None
        self._event_job_producer: EventJobProducer | None = None
        self._object_store: ObjectStore | None = None
        self._ml_enrollment_client: MlEnrollmentClient | None = None
        self._password_hasher: PasswordHasher | None = None
        self._token_service: TokenService | None = None
        self._permission_resolver: PermissionResolver | None = None
        self._auth_service: AuthService | None = None
        self._onboarding_service: OnboardingService | None = None
        self._student_service: StudentService | None = None
        self._event_service: EventService | None = None
        self._media_service: MediaService | None = None
        self._gallery_service: GalleryService | None = None
        self._dashboard_service: DashboardService | None = None
        self._listing_service: ListingService | None = None
        self._notification_service: NotificationService | None = None
        self._review_service: ReviewService | None = None

    @property
    def settings(self) -> Settings:
        """The active settings (read-only; routes read e.g. max_upload_mb)."""
        return self._s

    # ---- shared resources ----------------------------------------------

    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        if self._sessionmaker is None:
            with self._lock:
                if self._sessionmaker is None:
                    self._engine = make_engine(
                        self._s.database_url, echo=self._s.db_echo
                    )
                    self._sessionmaker = make_sessionmaker(self._engine)
        return self._sessionmaker

    # ---- adapters (one memoized instance each) -------------------------

    def school_repo(self) -> SchoolRepository:
        if self._school_repo is None:
            with self._lock:
                if self._school_repo is None:
                    cls = registry.resolve(
                        registry.SCHOOL_REPO_REGISTRY, self._s.repository_impl
                    )
                    self._school_repo = cls(self.sessionmaker())
        return self._school_repo

    def user_repo(self) -> UserRepository:
        if self._user_repo is None:
            with self._lock:
                if self._user_repo is None:
                    cls = registry.resolve(
                        registry.USER_REPO_REGISTRY, self._s.repository_impl
                    )
                    self._user_repo = cls(self.sessionmaker())
        return self._user_repo

    def student_repo(self) -> StudentRepository:
        if self._student_repo is None:
            with self._lock:
                if self._student_repo is None:
                    cls = registry.resolve(
                        registry.STUDENT_REPO_REGISTRY, self._s.repository_impl
                    )
                    self._student_repo = cls(self.sessionmaker())
        return self._student_repo

    def event_repo(self) -> EventRepository:
        if self._event_repo is None:
            with self._lock:
                if self._event_repo is None:
                    cls = registry.resolve(
                        registry.EVENT_REPO_REGISTRY, self._s.repository_impl
                    )
                    self._event_repo = cls(self.sessionmaker())
        return self._event_repo

    def media_repo(self) -> MediaRepository:
        if self._media_repo is None:
            with self._lock:
                if self._media_repo is None:
                    cls = registry.resolve(
                        registry.MEDIA_REPO_REGISTRY, self._s.repository_impl
                    )
                    self._media_repo = cls(self.sessionmaker())
        return self._media_repo

    def ml_results_reader(self) -> MlResultsReader:
        # Read-only reader over the ML-owned `matches` table (decisions/0028); the sole
        # coupling to the ML result schema. Postgres-only, like the repos.
        if self._ml_results_reader is None:
            with self._lock:
                if self._ml_results_reader is None:
                    cls = registry.resolve(
                        registry.ML_RESULTS_READER_REGISTRY, self._s.repository_impl
                    )
                    self._ml_results_reader = cls(self.sessionmaker())
        return self._ml_results_reader

    def match_correction_repo(self) -> MatchCorrectionRepository:
        if self._match_correction_repo is None:
            with self._lock:
                if self._match_correction_repo is None:
                    cls = registry.resolve(
                        registry.MATCH_CORRECTION_REPO_REGISTRY,
                        self._s.repository_impl,
                    )
                    self._match_correction_repo = cls(self.sessionmaker())
        return self._match_correction_repo

    def notification_reads_repo(self) -> NotificationReadRepository:
        if self._notification_reads_repo is None:
            with self._lock:
                if self._notification_reads_repo is None:
                    cls = registry.resolve(
                        registry.NOTIFICATION_READS_REPO_REGISTRY,
                        self._s.repository_impl,
                    )
                    self._notification_reads_repo = cls(self.sessionmaker())
        return self._notification_reads_repo

    # ---- notifications: the composite of configured channels (BP4) ------

    def notifier(self) -> NotificationChannel:
        if self._notifier is None:
            with self._lock:
                if self._notifier is None:
                    names = [
                        n.strip()
                        for n in self._s.notification_channels.split(",")
                        if n.strip()
                    ]
                    channels: list[NotificationChannel] = []
                    for name in names:
                        cls = registry.resolve(
                            registry.NOTIFICATION_CHANNEL_REGISTRY, name
                        )
                        channels.append(cls())  # log takes no args; future channels branch here
                    self._notifier = CompositeNotifier(channels)
        return self._notifier

    # ---- events: job producer (decisions/0027) -------------------------

    def event_job_producer(self) -> EventJobProducer:
        if self._event_job_producer is None:
            with self._lock:
                if self._event_job_producer is None:
                    cls = registry.resolve(
                        registry.EVENT_JOB_PRODUCER_REGISTRY,
                        self._s.event_job_producer_impl,
                    )
                    if self._s.event_job_producer_impl == "redis":
                        self._event_job_producer = cls(
                            self._s.redis_url, stream=self._s.queue_stream
                        )
                    else:  # inproc (offline dev)
                        self._event_job_producer = cls()
        return self._event_job_producer

    # ---- students: object store + ML client (decisions/0026) -----------

    def object_store(self) -> ObjectStore:
        if self._object_store is None:
            with self._lock:
                if self._object_store is None:
                    cls = registry.resolve(
                        registry.OBJECT_STORE_REGISTRY, self._s.object_store_impl
                    )
                    if self._s.object_store_impl == "supabase":
                        self._object_store = cls(
                            self._s.supabase_url,
                            self._s.supabase_key.get_secret_value(),
                            self._s.supabase_bucket,
                        )
                    else:  # local_fs (credential-free dev)
                        self._object_store = cls(self._s.object_store_dir)
        return self._object_store

    def ml_enrollment_client(self) -> MlEnrollmentClient:
        if self._ml_enrollment_client is None:
            with self._lock:
                if self._ml_enrollment_client is None:
                    cls = registry.resolve(
                        registry.ML_ENROLLMENT_CLIENT_REGISTRY,
                        self._s.ml_enrollment_client_impl,
                    )
                    if self._s.ml_enrollment_client_impl == "http":
                        self._ml_enrollment_client = cls(
                            self._s.ml_service_url,
                            timeout_s=self._s.ml_http_timeout_s,
                        )
                    else:  # fake (offline dev)
                        self._ml_enrollment_client = cls()
        return self._ml_enrollment_client

    # ---- auth (decisions/0024) -----------------------------------------

    def password_hasher(self) -> PasswordHasher:
        if self._password_hasher is None:
            with self._lock:
                if self._password_hasher is None:
                    cls = registry.resolve(
                        registry.PASSWORD_HASHER_REGISTRY, self._s.password_hasher_impl
                    )
                    self._password_hasher = cls()
        return self._password_hasher

    def token_service(self) -> TokenService:
        if self._token_service is None:
            with self._lock:
                if self._token_service is None:
                    cls = registry.resolve(
                        registry.TOKEN_SERVICE_REGISTRY, self._s.token_service_impl
                    )
                    # Fails loud here if BE_JWT_SECRET is empty (decisions/0024).
                    self._token_service = cls(
                        secret=self._s.jwt_secret.get_secret_value(),
                        algorithm=self._s.jwt_algorithm,
                        issuer=self._s.jwt_issuer,
                        access_ttl_s=self._s.access_token_ttl_s,
                        refresh_ttl_s=self._s.refresh_token_ttl_s,
                    )
        return self._token_service

    def permission_resolver(self) -> PermissionResolver:
        if self._permission_resolver is None:
            with self._lock:
                if self._permission_resolver is None:
                    cls = registry.resolve(
                        registry.PERMISSION_RESOLVER_REGISTRY,
                        self._s.permission_resolver_impl,
                    )
                    self._permission_resolver = cls()
        return self._permission_resolver

    def auth_service(self) -> AuthService:
        if self._auth_service is None:
            with self._lock:
                if self._auth_service is None:
                    self._auth_service = AuthService(
                        self.user_repo(),
                        self.password_hasher(),
                        self.token_service(),
                    )
        return self._auth_service

    def onboarding_service(self) -> OnboardingService:
        if self._onboarding_service is None:
            with self._lock:
                if self._onboarding_service is None:
                    self._onboarding_service = OnboardingService(
                        self.school_repo(),
                        self.user_repo(),
                        self.password_hasher(),
                    )
        return self._onboarding_service

    def student_service(self) -> StudentService:
        if self._student_service is None:
            with self._lock:
                if self._student_service is None:
                    self._student_service = StudentService(
                        self.student_repo(),
                        self.user_repo(),
                        self.school_repo(),
                        self.password_hasher(),
                        self.object_store(),
                        self.ml_enrollment_client(),
                        reference_photo_prefix=self._s.reference_photo_prefix,
                    )
        return self._student_service

    def event_service(self) -> EventService:
        if self._event_service is None:
            with self._lock:
                if self._event_service is None:
                    self._event_service = EventService(
                        self.event_repo(),
                        self.media_repo(),
                        self.event_job_producer(),
                    )
        return self._event_service

    def media_service(self) -> MediaService:
        if self._media_service is None:
            with self._lock:
                if self._media_service is None:
                    self._media_service = MediaService(
                        self.media_repo(),
                        self.event_repo(),
                        self.object_store(),
                        event_media_prefix=self._s.event_media_prefix,
                    )
        return self._media_service

    def gallery_service(self) -> GalleryService:
        if self._gallery_service is None:
            with self._lock:
                if self._gallery_service is None:
                    self._gallery_service = GalleryService(
                        self.ml_results_reader(),
                        self.student_repo(),
                        self.event_repo(),
                        self.media_repo(),
                        self.match_correction_repo(),
                        self.object_store(),
                        download_url_ttl_s=self._s.download_url_ttl_s,
                    )
        return self._gallery_service

    def review_service(self) -> ReviewService:
        if self._review_service is None:
            with self._lock:
                if self._review_service is None:
                    self._review_service = ReviewService(
                        self.ml_results_reader(),
                        self.match_correction_repo(),
                        self.media_repo(),
                        self.student_repo(),
                        self.event_repo(),
                    )
        return self._review_service

    def dashboard_service(self) -> DashboardService:
        if self._dashboard_service is None:
            with self._lock:
                if self._dashboard_service is None:
                    self._dashboard_service = DashboardService(
                        self.school_repo(),
                        self.student_repo(),
                        self.event_repo(),
                        self.media_repo(),
                        self.ml_results_reader(),
                        self.match_correction_repo(),
                    )
        return self._dashboard_service

    def listing_service(self) -> ListingService:
        if self._listing_service is None:
            with self._lock:
                if self._listing_service is None:
                    self._listing_service = ListingService(
                        self.school_repo(),
                        self.user_repo(),
                        self.student_repo(),
                        self.event_repo(),
                        self.media_repo(),
                        self.ml_results_reader(),
                    )
        return self._listing_service

    def notification_service(self) -> NotificationService:
        if self._notification_service is None:
            with self._lock:
                if self._notification_service is None:
                    self._notification_service = NotificationService(
                        self.event_repo(),
                        self.ml_results_reader(),
                        self.student_repo(),
                        self.notification_reads_repo(),
                        self.notifier(),
                        self.match_correction_repo(),
                    )
        return self._notification_service

    # ---- lifecycle -----------------------------------------------------

    async def check_readiness(self) -> dict[str, bool]:
        """Best-effort probe of the configured infra deps for ``/readyz``.

        Pings Postgres when a postgres repo is selected. Returns a per-dependency
        ok/not-ok map; an empty map means nothing to check.
        """
        from sqlalchemy import text

        checks: dict[str, bool] = {}
        if self._s.repository_impl == "postgres":
            try:
                async with asyncio.timeout(self._s.readiness_timeout_s):
                    async with self.sessionmaker()() as session:
                        await session.execute(text("SELECT 1"))
                checks["database"] = True
            except Exception:  # unreachable/slow/down -> not ready (bounded)
                checks["database"] = False
        return checks

    async def aclose(self) -> None:
        """Dispose shared resources. Safe to call once at shutdown."""
        # Close the Redis producer connection if one was built (redis impl only).
        producer_close = getattr(self._event_job_producer, "aclose", None)
        if producer_close is not None:
            await producer_close()
            self._event_job_producer = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sessionmaker = None
