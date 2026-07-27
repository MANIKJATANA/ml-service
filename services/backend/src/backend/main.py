"""FastAPI app factory for the backend / core system.

Mounts the health, auth, onboarding (schools/staff), student, event, media, gallery, and
student-self (`/me`) routers, maps domain errors to HTTP status codes, and at startup
configures structured logging and wires the composition-root container onto ``app.state``
so ``/readyz`` can probe dependencies; on shutdown it disposes the container.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend import __version__
from backend.api.routers import (
    analytics,
    audit,
    auth,
    classes,
    dashboard,
    event_categories,
    events,
    galleries,
    health,
    me,
    media,
    review,
    schools,
    staff,
    students,
)
from backend.deps import get_container
from backend.domain.errors import (
    AuthenticationError,
    AuthorizationError,
    BackendError,
    ConfigurationError,
    ConflictError,
    LimitExceededError,
    NotFoundError,
    UpstreamError,
    ValidationError,
)
from backend.domain.ports import RateLimiter
from backend.domain.tokens import TokenType
from backend.observability import metrics
from backend.observability.logging import configure_logging, get_logger
from backend.settings import settings
from backend.wiring import registry

_log = get_logger(__name__)

# Operational endpoints never rate-limited (probes must not flap; scrapes are internal).
_RATE_LIMIT_EXEMPT = frozenset({"/healthz", "/readyz", "/metrics"})


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level, json_output=settings.log_json)
    # Wire the container so /readyz can probe deps (cheap — no connections here).
    app.state.container = get_container()
    try:
        yield
    finally:
        await app.state.container.aclose()
        # Close the rate limiter if it holds a connection (the redis impl; memory has none).
        limiter_close = getattr(getattr(app.state, "rate_limiter", None), "aclose", None)
        if limiter_close is not None:
            await limiter_close()


def _register_error_handlers(app: FastAPI) -> None:
    async def on_not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    async def on_conflict(_: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    async def on_limit_exceeded(_: Request, exc: LimitExceededError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    async def on_validation(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    async def on_authentication(_: Request, exc: AuthenticationError) -> JSONResponse:
        # 401 + the scheme challenge, per RFC 6750.
        return JSONResponse(
            status_code=401,
            content={"detail": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        )

    async def on_authorization(_: Request, exc: AuthorizationError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    async def on_upstream(_: Request, exc: UpstreamError) -> JSONResponse:
        # A downstream dep (ML service) failed/unreachable — 502 Bad Gateway.
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    async def on_backend_error(_: Request, exc: BackendError) -> JSONResponse:
        # Base fallback — config/unclassified domain failures surface as 500.
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    app.add_exception_handler(NotFoundError, on_not_found)  # type: ignore[arg-type]
    app.add_exception_handler(ConflictError, on_conflict)  # type: ignore[arg-type]
    app.add_exception_handler(LimitExceededError, on_limit_exceeded)  # type: ignore[arg-type]
    app.add_exception_handler(ValidationError, on_validation)  # type: ignore[arg-type]
    app.add_exception_handler(AuthenticationError, on_authentication)  # type: ignore[arg-type]
    app.add_exception_handler(AuthorizationError, on_authorization)  # type: ignore[arg-type]
    app.add_exception_handler(UpstreamError, on_upstream)  # type: ignore[arg-type]
    app.add_exception_handler(BackendError, on_backend_error)  # type: ignore[arg-type]


def _install_metrics(app: FastAPI) -> None:
    """HTTP metrics middleware + the Prometheus scrape endpoint (decisions/0029)."""

    @app.middleware("http")
    async def _record_metrics(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = perf_counter()
        status_code = 500  # stays 500 if call_next raises before a response exists
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            # The matched ROUTE TEMPLATE (set on the scope after routing), never the
            # concrete path — unmatched requests collapse to one fixed label so a
            # hostile 404 scan can't explode the series count.
            route = request.scope.get("route")
            template = getattr(route, "path", None) or "__unmatched__"
            metrics.record_request(
                request.method, template, status_code, perf_counter() - start
            )

    @app.get("/metrics", tags=["observability"], include_in_schema=False)
    def prometheus_metrics() -> Response:
        body, content_type = metrics.render_latest()
        return Response(content=body, media_type=content_type)


def _build_rate_limiter() -> RateLimiter:
    """Build the configured rate limiter (memory | redis) via the registry."""
    cls = registry.resolve(registry.RATE_LIMITER_REGISTRY, settings.rate_limit_impl)
    if settings.rate_limit_impl == "redis":
        return cls(settings.redis_url)  # type: ignore[no-any-return]
    return cls()  # type: ignore[no-any-return]


def _install_rate_limit(app: FastAPI, rate_limiter: RateLimiter | None) -> None:
    """A fixed-window throttle (BP8c, decisions/0051): a global tier + a stricter tier on
    ``/v1/auth/*`` + a per-school tier (``school_id`` from the JWT). The first tier exceeded
    returns 429 + ``Retry-After``. Fail-open — any limiter error lets the request through, so
    a store outage never takes the API down. Not installed when disabled.

    The limiter is built once here (per app instance, not the process-global container), so
    the in-memory counters can't accumulate across a test suite's many ``create_app()`` calls.
    """
    if not settings.rate_limit_enabled:
        return
    limiter = rate_limiter or _build_rate_limiter()
    # Held on app.state so lifespan can close it (the redis impl) at shutdown.
    app.state.rate_limiter = limiter

    async def _school_id(request: Request) -> str | None:
        # Best-effort verified decode of the bearer access token (never trust an unverified
        # claim). Any failure — no/invalid token, a refresh token, an unbuildable token
        # service (empty secret) — skips the per-school tier; the global tier still applies.
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return None
        try:
            claims = get_container().token_service().decode(
                auth[7:].strip(), expected_type=TokenType.ACCESS
            )
            return claims.school_id
        except Exception:
            return None

    @app.middleware("http")
    async def _rate_limit(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Never throttle liveness/readiness probes or metric scrapes — a limited probe
        # would flap the deploy, and a scrape shouldn't consume a tenant's budget.
        if request.url.path in _RATE_LIMIT_EXEMPT:
            return await call_next(request)
        window = settings.rate_limit_window_s
        tiers: list[tuple[str, str, int]] = [
            ("global", "global", settings.rate_limit_global_per_min),
        ]
        if request.url.path.startswith("/v1/auth/"):
            tiers.append(("auth", "auth", settings.rate_limit_auth_per_min))
        school = await _school_id(request)
        if school:
            tiers.append(
                ("school", f"school:{school}", settings.rate_limit_school_per_min)
            )
        try:
            for scope, key, limit in tiers:
                result = await limiter.acquire(key, limit=limit, window_s=window)
                if not result.allowed:
                    metrics.record_rate_limit_rejection(scope)
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "rate limit exceeded"},
                        headers={"Retry-After": str(result.retry_after_s)},
                    )
        except Exception:  # fail-open — a limiter fault must never block the API
            _log.warning("rate_limit_check_failed", exc_info=True)
        return await call_next(request)


def _install_security_headers(app: FastAPI) -> None:
    """Defense-in-depth security headers on every API response (BP8c, decisions/0051).

    The browser never talks to the backend directly (only the Next BFF does), so these are
    a belt-and-suspenders layer; the browser-facing headers (incl. the CSP) live in the FE
    ``next.config``. Installed outermost so the headers land on error + 429 responses too.
    """
    if not settings.security_headers_enabled:
        return

    @app.middleware("http")
    async def _security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        # A JSON API loads nothing — a maximally-restrictive CSP is safe here.
        headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
        if settings.hsts_enabled:
            headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={settings.hsts_max_age_s}; includeSubDomains",
            )
        return response


def _install_cors(app: FastAPI) -> None:
    """Install CORS only when BE_CORS_ORIGINS lists at least one origin.

    Added after the metrics middleware so it is the outermost layer: preflight
    OPTIONS short-circuit here and don't inflate the request metrics.
    """
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if not origins:
        return
    if "*" in origins:
        # A credentialed wildcard makes Starlette reflect (and set allow-credentials on)
        # ANY origin, so any site could read authenticated responses. Fail loud (the
        # repo's config philosophy, cf. the empty jwt_secret) — require explicit origins.
        raise ConfigurationError(
            "BE_CORS_ORIGINS='*' is unsupported: a credentialed wildcard would reflect "
            "any origin. List explicit origins instead."
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def create_app(rate_limiter: RateLimiter | None = None) -> FastAPI:
    app = FastAPI(title="Backend", version=__version__, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(schools.router)
    app.include_router(staff.router)
    app.include_router(students.router)
    app.include_router(classes.router)
    app.include_router(events.router)
    app.include_router(event_categories.router)
    app.include_router(media.router)
    app.include_router(galleries.router)
    app.include_router(me.router)
    app.include_router(dashboard.router)
    app.include_router(analytics.router)
    app.include_router(review.router)
    app.include_router(audit.router)
    # Middleware runs in reverse order of registration (last added = outermost), so this
    # yields, outer→inner: security-headers → CORS → rate-limit → metrics → routes.
    # Rate-limit sits INSIDE CORS (preflight OPTIONS short-circuits at CORS, unthrottled) and
    # OUTSIDE metrics (a 429 is counted by its own rejection metric, not the HTTP counter);
    # security-headers is outermost so its headers reach the 429 + every error response.
    _install_metrics(app)
    _install_rate_limit(app, rate_limiter)
    _install_cors(app)
    _install_security_headers(app)
    _register_error_handlers(app)
    return app


app = create_app()
