"""Security-headers middleware (BP8c, decisions/0051).

Defense-in-depth headers on every backend response — a 200, an error, and the rate-limit
429 (proving the middleware is outermost) — with HSTS gated on ``hsts_enabled``.
"""

from __future__ import annotations

import pytest
from backend import main
from backend.settings import settings
from fastapi.testclient import TestClient


def _base_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "security_headers_enabled", True)
    monkeypatch.setattr(settings, "hsts_enabled", False)


def test_headers_present_on_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_headers(monkeypatch)
    client = TestClient(main.create_app())
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert "strict-transport-security" not in r.headers  # HSTS off by default


def test_headers_present_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # A 404 (no route, no DB) still carries the headers — they wrap every response.
    _base_headers(monkeypatch)
    client = TestClient(main.create_app())
    r = client.get("/v1/nope")
    assert r.status_code == 404
    assert r.headers["x-frame-options"] == "DENY"


def test_headers_on_rate_limit_429(monkeypatch: pytest.MonkeyPatch) -> None:
    # The security-headers middleware is outermost, so its headers reach the 429 the
    # rate-limit middleware returns.
    _base_headers(monkeypatch)
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_global_per_min", 1)
    client = TestClient(main.create_app())
    assert client.get("/v1/nope").status_code == 404
    r = client.get("/v1/nope")
    assert r.status_code == 429
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_hsts_present_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "security_headers_enabled", True)
    monkeypatch.setattr(settings, "hsts_enabled", True)
    monkeypatch.setattr(settings, "hsts_max_age_s", 12345)
    client = TestClient(main.create_app())
    r = client.get("/healthz")
    assert r.headers["strict-transport-security"] == "max-age=12345; includeSubDomains"


def test_headers_absent_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "security_headers_enabled", False)
    client = TestClient(main.create_app())
    r = client.get("/healthz")
    assert "x-frame-options" not in r.headers
    assert "content-security-policy" not in r.headers
