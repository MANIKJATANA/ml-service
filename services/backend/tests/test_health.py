"""Health-probe tests. No live DB: ``/readyz`` reports ready before the container
is wired, and the wired path is exercised with a stub container."""

from __future__ import annotations

from backend.main import app, create_app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_healthz() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readyz_before_wiring_is_ready() -> None:
    # Bare TestClient runs no lifespan, so app.state.container is unset.
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


class _StubContainer:
    def __init__(self, checks: dict[str, bool]) -> None:
        self._checks = checks

    async def check_readiness(self) -> dict[str, bool]:
        return self._checks


def test_readyz_ready_when_deps_up() -> None:
    app_ = create_app()
    app_.state.container = _StubContainer({"database": True})
    resp = TestClient(app_).get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "checks": {"database": True}}


def test_readyz_not_ready_when_dep_down() -> None:
    app_ = create_app()
    app_.state.container = _StubContainer({"database": False})
    resp = TestClient(app_).get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"
