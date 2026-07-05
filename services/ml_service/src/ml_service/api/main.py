"""FastAPI app factory for the ML service.

Mounts the health + enrollment routers, exposes Prometheus metrics at
``/metrics``, and maps domain errors to HTTP status codes. At startup it
configures structured logging + (opt-in) tracing and wires the composition-root
container onto ``app.state`` so ``/readyz`` can probe dependencies; on shutdown it
disposes the container.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from ml_service import __version__
from ml_service.api.deps import get_container
from ml_service.api.routes import enrollment, health
from ml_service.domain.errors import EnrollmentError, MLServiceError
from ml_service.observability import metrics
from ml_service.observability.logging import configure_logging
from ml_service.observability.tracing import configure_tracing
from ml_service.wiring.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level, json_output=settings.log_json)
    configure_tracing(settings.service_name, otlp_endpoint=settings.otel_exporter_otlp_endpoint)
    # Wire the container so /readyz can probe deps (cheap — no model load here).
    app.state.container = get_container()
    try:
        yield
    finally:
        await app.state.container.aclose()


def _register_error_handlers(app: FastAPI) -> None:
    async def on_enrollment_error(_: Request, exc: EnrollmentError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    async def on_ml_error(_: Request, exc: MLServiceError) -> JSONResponse:
        # Configuration / dependency failures — surface as a server error.
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    app.add_exception_handler(EnrollmentError, on_enrollment_error)  # type: ignore[arg-type]
    app.add_exception_handler(MLServiceError, on_ml_error)  # type: ignore[arg-type]


def create_app() -> FastAPI:
    app = FastAPI(title="ML Service", version=__version__, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(enrollment.router)
    if settings.enable_test_ui:  # dev-only browser test harness (decisions/0019)
        from ml_service.api.routes import dev_ui

        app.include_router(dev_ui.router)

    @app.get("/metrics", tags=["observability"], include_in_schema=False)
    def prometheus_metrics() -> Response:
        body, content_type = metrics.render_latest()
        return Response(content=body, media_type=content_type)

    _register_error_handlers(app)
    return app


app = create_app()
