"""Enrollment API routes + /readyz gating.

The route is driven by a real :class:`EnrollmentService` wired to the shared
test-only port stubs (``fakes.py``) via ``dependency_overrides`` — no models, no
network. A fresh ``create_app()`` per module keeps state isolated from the shared
health-test client.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fakes import (
    StubDetector,
    StubEmbedder,
    StubMediaStore,
    StubReferencePhotoRepository,
    StubVectorIndex,
)
from fastapi.testclient import TestClient
from ml_service.api.deps import get_enrollment_service
from ml_service.api.main import create_app
from ml_service.orchestration.enrollment import EnrollmentService

URI = "s3://p1.jpg"


class _Fixture:
    def __init__(self) -> None:
        self.refrepo = StubReferencePhotoRepository()
        self.media = StubMediaStore({URI: b"img-bytes"})
        self.index = StubVectorIndex()
        self.service = EnrollmentService(
            self.refrepo, self.media, StubDetector(), StubEmbedder(), self.index
        )


@pytest.fixture
def fx() -> Iterator[tuple[TestClient, _Fixture]]:
    f = _Fixture()
    app = create_app()
    app.dependency_overrides[get_enrollment_service] = lambda: f.service
    yield TestClient(app), f


def test_enroll_with_uris_returns_per_photo_results(
    fx: tuple[TestClient, _Fixture],
) -> None:
    client, f = fx
    resp = client.post(
        "/v1/schools/school-1/students/stu-1/enroll",
        json={"photo_uris": [URI]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["school_id"] == "school-1"
    assert body["student_id"] == "stu-1"
    assert body["embeddings_stored"] == 1
    assert body["photo_results"] == [{"index": 0, "status": "enrolled", "detail": None}]
    assert ("school-1", "stu-1") in f.index.store


def test_enroll_empty_uris_is_400(fx: tuple[TestClient, _Fixture]) -> None:
    client, _ = fx
    resp = client.post(
        "/v1/schools/s/students/t/enroll",
        json={"photo_uris": []},
    )
    assert resp.status_code == 400
    assert "delete()" in resp.json()["detail"]


def test_refresh_without_uris_uses_stored(fx: tuple[TestClient, _Fixture]) -> None:
    client, f = fx
    # Seed stored URIs, then refresh (no body uris).
    import asyncio

    asyncio.run(f.refrepo.replace("s", "t", [URI]))
    resp = client.post("/v1/schools/s/students/t/enroll", json={})
    assert resp.status_code == 200
    assert resp.json()["embeddings_stored"] == 1


def test_delete_student_returns_204(fx: tuple[TestClient, _Fixture]) -> None:
    client, f = fx
    resp = client.delete("/v1/schools/s/students/t")
    assert resp.status_code == 204
    assert ("s", "t") in f.index.deletes


class _FakeContainer:
    def __init__(self, checks: dict[str, bool]) -> None:
        self._checks = checks

    async def check_readiness(self) -> dict[str, bool]:
        return self._checks


def test_readyz_ready_when_deps_up() -> None:
    app = create_app()
    app.state.container = _FakeContainer({"database": True, "redis": True})
    resp = TestClient(app).get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_readyz_503_when_dep_down() -> None:
    app = create_app()
    app.state.container = _FakeContainer({"database": False, "redis": True})
    resp = TestClient(app).get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"
