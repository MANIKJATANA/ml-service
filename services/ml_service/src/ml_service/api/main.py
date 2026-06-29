"""FastAPI app factory for the ML service.

Scaffold only: exposes liveness/readiness probes. Enrollment routes
(POST/DELETE /v1/students) land when the EnrollmentService is implemented.
"""

from fastapi import FastAPI

from ml_service import __version__
from ml_service.wiring.settings import settings


def create_app() -> FastAPI:
    app = FastAPI(title="ML Service", version=__version__)

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        """Liveness — process is up."""
        return {"status": "ok", "service": settings.service_name}

    @app.get("/readyz", tags=["health"])
    def readyz() -> dict[str, str]:
        """Readiness — dependency checks added as adapters are wired in."""
        return {"status": "ready"}

    return app


app = create_app()
