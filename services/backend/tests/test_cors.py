"""CORS is installed only when BE_CORS_ORIGINS is set (decisions/0029)."""

from __future__ import annotations

import pytest
from backend import main
from backend.domain.errors import ConfigurationError
from backend.settings import settings
from fastapi.testclient import TestClient


def test_cors_headers_present_for_allowed_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "cors_origins", "http://localhost:3000")
    client = TestClient(main.create_app())

    resp = client.get("/healthz", headers={"Origin": "http://localhost:3000"})

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_no_cors_headers_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "cors_origins", "")
    client = TestClient(main.create_app())

    resp = client.get("/healthz", headers={"Origin": "http://localhost:3000"})

    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


def test_wildcard_origin_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # A credentialed wildcard is a security downgrade — the app must fail loud.
    monkeypatch.setattr(settings, "cors_origins", "*")
    with pytest.raises(ConfigurationError):
        main.create_app()
