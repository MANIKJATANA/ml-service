"""FastAPI app factory for the ML service.

Mounts the health + enrollment routers and maps domain errors to HTTP status
codes. At startup it wires the composition-root container onto ``app.state`` so
``/readyz`` can probe dependencies; on shutdown it disposes the container.

A TEMPORARY wiring demo (see ``ml_service.demo``) is still mounted — it and its
Redis consumer are removed in Phase 4 once the real paths are exercised end to
end (decisions/0006).
"""

import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ml_service import __version__, demo
from ml_service.api.deps import get_container
from ml_service.api.routes import enrollment, health
from ml_service.domain.errors import EnrollmentError, MLServiceError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Wire the container so /readyz can probe deps (cheap — no model load here).
    app.state.container = get_container()
    # TEMP: set up the demo table and start the Redis consumer.
    await demo.ensure_table()
    task = demo.start_consumer()
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(Exception):
            await task
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
    _register_error_handlers(app)
    app.include_router(demo.router)  # TEMP
    return app


app = create_app()
