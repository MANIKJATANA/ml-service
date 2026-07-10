"""FastAPI app factory for the backend / core system.

Mounts the health, auth, onboarding (schools/staff), student, event, media, gallery, and
student-self (`/me`) routers, maps domain errors to HTTP status codes, and at startup
configures structured logging and wires the composition-root container onto ``app.state``
so ``/readyz`` can probe dependencies; on shutdown it disposes the container.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend import __version__
from backend.api.routers import (
    auth,
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
    ConflictError,
    LimitExceededError,
    NotFoundError,
    UpstreamError,
    ValidationError,
)
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
    _register_error_handlers(app)
    return app


app = create_app()
