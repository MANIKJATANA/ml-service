"""The app maps domain errors to HTTP status codes (main.py exception handlers)."""

from __future__ import annotations

import pytest
from backend.domain.errors import (
    ConfigurationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from backend.main import create_app
from fastapi.testclient import TestClient

_CASES: dict[str, tuple[Exception, int]] = {
    "notfound": (NotFoundError("boom"), 404),
    "conflict": (ConflictError("boom"), 409),
    "validation": (ValidationError("boom"), 400),
    # No dedicated handler -> falls through to the BackendError base handler -> 500.
    "config": (ConfigurationError("boom"), 500),
}


@pytest.mark.parametrize("kind", list(_CASES))
def test_domain_error_maps_to_status(kind: str) -> None:
    app = create_app()

    @app.get("/_boom/{which}")
    async def boom(which: str) -> None:
        raise _CASES[which][0]

    resp = TestClient(app).get(f"/_boom/{kind}")
    assert resp.status_code == _CASES[kind][1]
    assert resp.json()["detail"] == "boom"
