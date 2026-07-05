"""Health probes: ``/healthz`` (liveness) and ``/readyz`` (readiness).

``/readyz`` reports a hard dependency gate **once the app has wired its
container** (set on ``app.state.container`` at startup): it pings the configured
Postgres/Redis and returns 503 if any is down. Before wiring — e.g. a bare
``TestClient(app)`` with no lifespan — it reports ready (process-level liveness),
so unit tests need no live backends.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from ml_service.wiring.settings import settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness — process is up."""
    return {"status": "ok", "service": settings.service_name}


@router.get("/readyz")
async def readyz(request: Request, response: Response) -> dict[str, object]:
    """Readiness — dependency checks once the container is wired."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        return {"status": "ready"}
    checks = await container.check_readiness()
    if all(checks.values()):
        return {"status": "ready", "checks": checks}
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "not_ready", "checks": checks}
