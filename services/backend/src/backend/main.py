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
    auth,
    dashboard,
    events,
    galleries,
    health,
    me,
    media,
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
from backend.observability import metrics
from backend.observability.logging import configure_logging
from backend.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level, json_output=settings.log_json)
    # Wire the container so /readyz can probe deps (cheap — no connections here).
    app.state.container = get_container()
    try:
        yield
    finally:
        await app.state.container.aclose()


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


def create_app() -> FastAPI:
    app = FastAPI(title="Backend", version=__version__, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(schools.router)
    app.include_router(staff.router)
    app.include_router(students.router)
    app.include_router(events.router)
    app.include_router(media.router)
    app.include_router(galleries.router)
    app.include_router(me.router)
    app.include_router(dashboard.router)
    _install_metrics(app)
    _install_cors(app)
    _register_error_handlers(app)
    return app


app = create_app()
