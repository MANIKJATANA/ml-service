"""FastAPI app factory for the backend / core system.

Health probes only for now — the real upload/storage/notification/distribution
surface lands in a later phase.
"""

from fastapi import FastAPI

from backend import __version__
from backend.settings import settings


def create_app() -> FastAPI:
    app = FastAPI(title="Backend", version=__version__)

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": settings.service_name}

    @app.get("/readyz", tags=["health"])
    def readyz() -> dict[str, str]:
        return {"status": "ready"}

    return app


app = create_app()
