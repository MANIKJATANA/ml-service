"""FastAPI app factory for the backend / core system.

Health probes + a TEMPORARY wiring demo (see backend.demo).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend import __version__, demo
from backend.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await demo.ensure_table()  # TEMP
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Backend", version=__version__, lifespan=lifespan)

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": settings.service_name}

    @app.get("/readyz", tags=["health"])
    def readyz() -> dict[str, str]:
        return {"status": "ready"}

    app.include_router(demo.router)  # TEMP
    return app


app = create_app()
