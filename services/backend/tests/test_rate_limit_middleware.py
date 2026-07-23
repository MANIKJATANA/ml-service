"""Rate-limit middleware (BP8c, decisions/0051).

Uses paths that never touch the DB — /healthz (global tier only) and a 404 under /v1/... (so
the request flows through the middleware but no route/DB runs) — so the limiter is exercised
in isolation. The per-app limiter (a fresh one per create_app) means no cross-test bleed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from backend import main
from backend.domain.models import RateLimitResult
from backend.settings import settings
from fastapi.testclient import TestClient


def test_global_limit_trips_429_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    # /v1/nope 404s (no route, no DB) but still counts against the global tier.
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_global_per_min", 3)
    client = TestClient(main.create_app())
    for _ in range(3):
        assert client.get("/v1/nope").status_code == 404
    resp = client.get("/v1/nope")
    assert resp.status_code == 429
    assert resp.json()["detail"] == "rate limit exceeded"
    assert 0 < int(resp.headers["retry-after"]) <= settings.rate_limit_window_s


def test_probes_and_metrics_are_exempt(monkeypatch: pytest.MonkeyPatch) -> None:
    # Liveness/readiness/metrics are never throttled (a limited probe would flap the deploy).
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_global_per_min", 1)
    client = TestClient(main.create_app())
    for _ in range(4):  # well past the global limit of 1
        assert client.get("/healthz").status_code == 200
    assert client.get("/metrics").status_code == 200


def test_disabled_never_throttles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "rate_limit_global_per_min", 1)
    client = TestClient(main.create_app())
    for _ in range(5):
        assert client.get("/v1/nope").status_code == 404


def test_malformed_auth_header_falls_through_to_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A bare/garbage/invalid bearer must not crash the school decode — global tier only.
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    client = TestClient(main.create_app())
    for hdr in (
        {"Authorization": "Bearer "},
        {"Authorization": "garbage"},
        {"Authorization": "Bearer not.a.jwt"},
    ):
        assert client.get("/v1/nope", headers=hdr).status_code == 404


def test_rejection_metric_increments_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_global_per_min", 1)
    client = TestClient(main.create_app())
    assert client.get("/v1/nope").status_code == 404
    assert client.get("/v1/nope").status_code == 429
    body = client.get("/metrics").text  # /metrics is exempt, so this won't 429
    assert 'backend_rate_limit_rejections_total{scope="global"}' in body


def test_auth_tier_is_stricter(monkeypatch: pytest.MonkeyPatch) -> None:
    # The /v1/auth/* paths get their own stricter bucket. A 404 under /v1/auth/ still counts
    # against the auth tier (the middleware keys on the path prefix, before routing) — no DB.
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_global_per_min", 1000)
    monkeypatch.setattr(settings, "rate_limit_auth_per_min", 2)
    client = TestClient(main.create_app())
    for _ in range(2):
        assert client.get("/v1/auth/nope").status_code == 404
    assert client.get("/v1/auth/nope").status_code == 429


def test_per_school_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    # A valid token contributes a per-school bucket. Stub the token decode so no real
    # secret/DB is needed; the stub reads the school_id straight from the bearer value, so
    # two "schools" get independent buckets.
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_global_per_min", 1000)
    monkeypatch.setattr(settings, "rate_limit_auth_per_min", 1000)
    monkeypatch.setattr(settings, "rate_limit_school_per_min", 2)

    class _TS:
        def decode(self, token: str, *, expected_type: object) -> object:
            return SimpleNamespace(school_id=token)

    monkeypatch.setattr(main, "get_container", lambda: SimpleNamespace(token_service=_TS))
    client = TestClient(main.create_app())

    a = {"Authorization": "Bearer school-a"}
    b = {"Authorization": "Bearer school-b"}
    for _ in range(2):
        assert client.get("/v1/nope", headers=a).status_code == 404
    assert client.get("/v1/nope", headers=a).status_code == 429  # school-a exhausted
    assert client.get("/v1/nope", headers=b).status_code == 404  # school-b independent


def test_fails_open_when_limiter_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # A broken limiter must never take the API down — the request passes through.
    monkeypatch.setattr(settings, "rate_limit_enabled", True)

    class _Boom:
        async def acquire(self, key: str, *, limit: int, window_s: int) -> RateLimitResult:
            raise RuntimeError("limiter down")

    client = TestClient(main.create_app(rate_limiter=_Boom()))
    assert client.get("/healthz").status_code == 200
