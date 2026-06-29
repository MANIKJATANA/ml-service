"""FastAPI app factory for the backend / core system.

Scaffold only: liveness/readiness probes. Domain routes land as features arrive.
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
