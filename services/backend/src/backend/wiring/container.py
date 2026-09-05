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
from backend.domain.errors import ConfigurationError
from backend.domain.ports import (
    AdminActionAuditRepository,
    DownloadAuditRepository,
    EventCategoryRepository,
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
    PlatformConfigRepository,
    SchoolRepository,
    StudentGroupRepository,
    StudentRepository,
    TeacherClassRepository,
    Thumbnailer,
    TokenService,
    UserRepository,
    WhatsAppSender,
    WhatsAppSendLogRepository,
)
from backend.services.admin_action_audit_service import AdminActionAuditService
from backend.services.analytics_service import AnalyticsService
from backend.services.audit_service import AuditService
from backend.services.auth_service import AuthService
from backend.services.class_service import ClassService
from backend.services.dashboard_service import DashboardService
from backend.services.delegation_service import DelegationService
from backend.services.engagement_service import EngagementService
from backend.services.event_category_service import EventCategoryService
from backend.services.event_service import EventService
from backend.services.gallery_service import GalleryService
from backend.services.listing_service import ListingService
from backend.services.media_service import MediaService
from backend.services.notification_service import NotificationService
from backend.services.onboarding_service import OnboardingService
from backend.services.platform_config_service import PlatformConfigService
from backend.services.review_service import ReviewService
from backend.services.student_service import StudentService
from backend.services.whatsapp_share_service import WhatsAppShareService
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
        self._student_group_repo: StudentGroupRepository | None = None
        self._teacher_class_repo: TeacherClassRepository | None = None
        self._event_repo: EventRepository | None = None
        self._event_category_repo: EventCategoryRepository | None = None
        self._media_repo: MediaRepository | None = None
        self._ml_results_reader: MlResultsReader | None = None
        self._match_correction_repo: MatchCorrectionRepository | None = None
        self._download_audit_repo: DownloadAuditRepository | None = None
        self._admin_action_audit_repo: AdminActionAuditRepository | None = None
        self._notification_reads_repo: NotificationReadRepository | None = None
        self._notifier: NotificationChannel | None = None
        self._event_job_producer: EventJobProducer | None = None
        self._object_store: ObjectStore | None = None
        self._thumbnailer: Thumbnailer | None = None
        self._ml_enrollment_client: MlEnrollmentClient | None = None
        self._whatsapp_sender: WhatsAppSender | None = None
        self._platform_config_repo: PlatformConfigRepository | None = None
        self._platform_config_service: PlatformConfigService | None = None
        self._whatsapp_send_log_repo: WhatsAppSendLogRepository | None = None
        self._whatsapp_share_service: WhatsAppShareService | None = None
        self._password_hasher: PasswordHasher | None = None
        self._token_service: TokenService | None = None
        self._permission_resolver: PermissionResolver | None = None
        self._auth_service: AuthService | None = None
        self._onboarding_service: OnboardingService | None = None
        self._student_service: StudentService | None = None
        self._class_service: ClassService | None = None
        self._delegation_service: DelegationService | None = None
        self._event_service: EventService | None = None
        self._event_category_service: EventCategoryService | None = None
        self._media_service: MediaService | None = None
        self._gallery_service: GalleryService | None = None
        self._audit_service: AuditService | None = None
        self._admin_action_audit_service: AdminActionAuditService | None = None
        self._dashboard_service: DashboardService | None = None
        self._analytics_service: AnalyticsService | None = None
        self._engagement_service: EngagementService | None = None
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

    def student_group_repo(self) -> StudentGroupRepository:
        if self._student_group_repo is None:
            with self._lock:
                if self._student_group_repo is None:
                    cls = registry.resolve(
                        registry.STUDENT_GROUP_REPO_REGISTRY, self._s.repository_impl
                    )
                    self._student_group_repo = cls(self.sessionmaker())
        return self._student_group_repo

    def teacher_class_repo(self) -> TeacherClassRepository:
        if self._teacher_class_repo is None:
            with self._lock:
                if self._teacher_class_repo is None:
                    cls = registry.resolve(
                        registry.TEACHER_CLASS_REPO_REGISTRY, self._s.repository_impl
                    )
                    self._teacher_class_repo = cls(self.sessionmaker())
        return self._teacher_class_repo

    def event_repo(self) -> EventRepository:
        if self._event_repo is None:
            with self._lock:
                if self._event_repo is None:
                    cls = registry.resolve(
                        registry.EVENT_REPO_REGISTRY, self._s.repository_impl
                    )
                    self._event_repo = cls(self.sessionmaker())
        return self._event_repo

    def event_category_repo(self) -> EventCategoryRepository:
        if self._event_category_repo is None:
            with self._lock:
                if self._event_category_repo is None:
                    cls = registry.resolve(
                        registry.EVENT_CATEGORY_REPO_REGISTRY, self._s.repository_impl
                    )
                    self._event_category_repo = cls(self.sessionmaker())
        return self._event_category_repo

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

    def download_audit_repo(self) -> DownloadAuditRepository:
        if self._download_audit_repo is None:
            with self._lock:
                if self._download_audit_repo is None:
                    cls = registry.resolve(
                        registry.DOWNLOAD_AUDIT_REPO_REGISTRY,
                        self._s.repository_impl,
                    )
                    self._download_audit_repo = cls(self.sessionmaker())
        return self._download_audit_repo

    def admin_action_audit_repo(self) -> AdminActionAuditRepository:
        if self._admin_action_audit_repo is None:
            with self._lock:
                if self._admin_action_audit_repo is None:
                    cls = registry.resolve(
                        registry.ADMIN_ACTION_AUDIT_REPO_REGISTRY,
                        self._s.repository_impl,
                    )
                    self._admin_action_audit_repo = cls(self.sessionmaker())
        return self._admin_action_audit_repo

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

    def thumbnailer(self) -> Thumbnailer:
        if self._thumbnailer is None:
            with self._lock:
                if self._thumbnailer is None:
                    cls = registry.resolve(
                        registry.THUMBNAILER_REGISTRY, self._s.thumbnailer_impl
                    )
                    self._thumbnailer = cls(
                        max_edge=self._s.image_thumbnail_max_edge,
                        quality=self._s.image_thumbnail_quality,
                    )
        return self._thumbnailer

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

    # ---- platform config (W-live-test) ---------------------------------

    def platform_config_repo(self) -> PlatformConfigRepository:
        if self._platform_config_repo is None:
            with self._lock:
                if self._platform_config_repo is None:
                    cls = registry.resolve(
                        registry.PLATFORM_CONFIG_REPO_REGISTRY,
                        self._s.repository_impl,
                    )
                    self._platform_config_repo = cls(self.sessionmaker())
        return self._platform_config_repo

    def platform_config_service(self) -> PlatformConfigService:
        if self._platform_config_service is None:
            with self._lock:
                if self._platform_config_service is None:
                    self._platform_config_service = PlatformConfigService(
                        self.platform_config_repo(),
                    )
        return self._platform_config_service

    # ---- WhatsApp (W1) -------------------------------------------------

    async def _meta_token(self) -> str:
        """Resolve the Meta access token FRESH per send from the DB ONLY (``platform_config``,
        edited at Platform → WhatsApp) — there is deliberately NO env fallback (0098), so a stale
        ``.env`` value can never be silently used. Returns "" when unset (a send then fails
        clearly). Bound as the Meta sender's ``token_provider`` so a UI edit takes effect on the
        next send without a rebuild. The token is NEVER logged."""
        cfg = await self.platform_config_repo().get()
        return (cfg.meta_access_token if cfg else None) or ""

    async def _meta_phone_number_id(self) -> str:
        """Resolve the Meta sender phone-number ID FRESH per send from the DB ONLY (the platform
        ``sender_number``, edited at Platform → WhatsApp) — NO env fallback (0098). Returns "" when
        unset. Bound as the Meta sender's ``phone_number_id_provider`` so a UI edit takes effect on
        the next send (no rebuild)."""
        cfg = await self.platform_config_repo().get()
        return (cfg.sender_number if cfg else None) or ""

    def whatsapp_sender(self) -> WhatsAppSender:
        # Config-selected (BE_WHATSAPP_SENDER_IMPL) sender. fake = credential-free default;
        # gupshup = the Gupshup BSP; meta = the direct Meta WhatsApp Cloud API. Each real
        # provider's ONE platform secret is read from settings HERE and never logged.
        if self._whatsapp_sender is None:
            with self._lock:
                if self._whatsapp_sender is None:
                    impl = self._s.whatsapp_sender_impl
                    cls = registry.resolve(registry.WHATSAPP_SENDER_REGISTRY, impl)
                    if impl == "fake":
                        self._whatsapp_sender = cls()
                    elif impl == "gupshup":
                        self._whatsapp_sender = cls(
                            api_key=self._s.whatsapp_api_key.get_secret_value(),
                            base_url=self._s.whatsapp_base_url,
                            app_name=self._s.whatsapp_app_name,
                            timeout_s=self._s.whatsapp_http_timeout_s,
                        )
                    elif impl == "meta":
                        # W-live-test: the token AND the sender phone-number ID are resolved FRESH
                        # per send via _meta_token / _meta_phone_number_id (DB-stored first, env
                        # fallback) — never static kwargs — so a UI edit takes effect on the next
                        # send. The sender stays memoized (the providers are bound methods; only the
                        # values they return vary per call).
                        self._whatsapp_sender = cls(
                            token_provider=self._meta_token,
                            phone_number_id_provider=self._meta_phone_number_id,
                            api_version=self._s.whatsapp_meta_api_version,
                            base_url=self._s.whatsapp_meta_base_url,
                            template_lang=self._s.whatsapp_meta_template_lang,
                            timeout_s=self._s.whatsapp_http_timeout_s,
                        )
                    else:  # a registry entry with no construction branch (shouldn't happen)
                        raise ConfigurationError(
                            f"unsupported whatsapp_sender_impl: {impl!r}"
                        )
        return self._whatsapp_sender

    def whatsapp_send_log_repo(self) -> WhatsAppSendLogRepository:
        if self._whatsapp_send_log_repo is None:
            with self._lock:
                if self._whatsapp_send_log_repo is None:
                    cls = registry.resolve(
                        registry.WHATSAPP_SEND_LOG_REPO_REGISTRY,
                        self._s.repository_impl,
                    )
                    self._whatsapp_send_log_repo = cls(self.sessionmaker())
        return self._whatsapp_send_log_repo

    def whatsapp_share_service(self) -> WhatsAppShareService:
        # W2: the FIRST place whatsapp_sender() is wired into a service. Composes the platform
        # config service (the sole WhatsApp config — sender/template/interim, 0099) + the gallery
        # service (its BP5 overlay gives the student's EFFECTIVE media — never re-derived) + the
        # object store / thumbnailer / sender / send-log + the send knobs.
        if self._whatsapp_share_service is None:
            with self._lock:
                if self._whatsapp_share_service is None:
                    self._whatsapp_share_service = WhatsAppShareService(
                        self.platform_config_service(),
                        self.gallery_service(),
                        self.student_repo(),
                        self.object_store(),
                        self.thumbnailer(),
                        self.whatsapp_sender(),
                        self.whatsapp_send_log_repo(),
                        default_sender_number=self._s.whatsapp_default_sender_number,
                        download_url_ttl_s=self._s.download_url_ttl_s,
                        image_max_edge=self._s.whatsapp_image_max_edge,
                        image_quality=self._s.whatsapp_image_quality,
                        image_max_bytes=self._s.whatsapp_image_max_bytes,
                        image_quality_floor=self._s.whatsapp_image_quality_floor,
                        monthly_send_cap=self._s.whatsapp_monthly_send_cap,
                        variant_prefix=self._s.whatsapp_variant_prefix,
                    )
        return self._whatsapp_share_service

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
                        self.event_category_repo(),
                        self.admin_action_audit_repo(),
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
                        self.thumbnailer(),
                        self.student_group_repo(),
                        self.admin_action_audit_repo(),
                        reference_photo_prefix=self._s.reference_photo_prefix,
                        download_url_ttl_s=self._s.download_url_ttl_s,
                    )
        return self._student_service

    def class_service(self) -> ClassService:
        if self._class_service is None:
            with self._lock:
                if self._class_service is None:
                    self._class_service = ClassService(
                        self.student_group_repo(),
                        self.student_repo(),
                    )
        return self._class_service

    def delegation_service(self) -> DelegationService:
        if self._delegation_service is None:
            with self._lock:
                if self._delegation_service is None:
                    self._delegation_service = DelegationService(
                        self.teacher_class_repo(),
                        self.student_group_repo(),
                        self.user_repo(),
                    )
        return self._delegation_service

    def event_service(self) -> EventService:
        if self._event_service is None:
            with self._lock:
                if self._event_service is None:
                    self._event_service = EventService(
                        self.event_repo(),
                        self.media_repo(),
                        self.event_job_producer(),
                        self.event_category_repo(),
                        self.student_group_repo(),
                        self.user_repo(),
                        inflight_stale_s=self._s.event_inflight_stale_s,
                    )
        return self._event_service

    def event_category_service(self) -> EventCategoryService:
        if self._event_category_service is None:
            with self._lock:
                if self._event_category_service is None:
                    self._event_category_service = EventCategoryService(
                        self.event_category_repo(),
                    )
        return self._event_category_service

    def media_service(self) -> MediaService:
        if self._media_service is None:
            with self._lock:
                if self._media_service is None:
                    self._media_service = MediaService(
                        self.media_repo(),
                        self.event_repo(),
                        self.object_store(),
                        self.thumbnailer(),
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
                        self.download_audit_repo(),
                        download_url_ttl_s=self._s.download_url_ttl_s,
                    )
        return self._gallery_service

    def audit_service(self) -> AuditService:
        if self._audit_service is None:
            with self._lock:
                if self._audit_service is None:
                    self._audit_service = AuditService(
                        self.download_audit_repo(),
                        self.media_repo(),
                        self.event_repo(),
                        self.student_repo(),
                        self.user_repo(),
                    )
        return self._audit_service

    def admin_action_audit_service(self) -> AdminActionAuditService:
        if self._admin_action_audit_service is None:
            with self._lock:
                if self._admin_action_audit_service is None:
                    self._admin_action_audit_service = AdminActionAuditService(
                        self.admin_action_audit_repo(),
                        self.user_repo(),
                    )
        return self._admin_action_audit_service

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
                        self.user_repo(),
                    )
        return self._dashboard_service

    def analytics_service(self) -> AnalyticsService:
        if self._analytics_service is None:
            with self._lock:
                if self._analytics_service is None:
                    self._analytics_service = AnalyticsService(
                        self.school_repo(),
                        self.user_repo(),
                        self.student_repo(),
                        self.event_repo(),
                        self.media_repo(),
                        self.notification_reads_repo(),
                        self.match_correction_repo(),
                        self.download_audit_repo(),
                        self.whatsapp_send_log_repo(),
                    )
        return self._analytics_service

    def engagement_service(self) -> EngagementService:
        if self._engagement_service is None:
            with self._lock:
                if self._engagement_service is None:
                    self._engagement_service = EngagementService(
                        self.student_repo(),
                        self.ml_results_reader(),
                        self.match_correction_repo(),
                        self.notification_reads_repo(),
                        self.download_audit_repo(),
                    )
        return self._engagement_service

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
                        self.download_audit_repo(),
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
