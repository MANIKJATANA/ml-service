"""FastAPI app factory for the ML service.

Health probes + a TEMPORARY wiring demo (see ml_service.demo). The demo router
and its Redis consumer will be removed once real routes exist.
"""

import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ml_service import __version__, demo
from ml_service.wiring.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # TEMP: set up the demo table and start the Redis consumer.
    await demo.ensure_table()
    task = demo.start_consumer()
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(Exception):
            await task


def create_app() -> FastAPI:
    app = FastAPI(title="ML Service", version=__version__, lifespan=lifespan)

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        """Liveness — process is up."""
        return {"status": "ok", "service": settings.service_name}

    @app.get("/readyz", tags=["health"])
    def readyz() -> dict[str, str]:
        """Readiness — dependency checks added as adapters are wired in."""
        return {"status": "ready"}

    app.include_router(demo.router)  # TEMP
    return app


app = create_app()
