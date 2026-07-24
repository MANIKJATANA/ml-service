"""Pytest configuration for the backend tests.

pytest runs with ``--import-mode=importlib`` (root pyproject), which does not add
test directories to ``sys.path``. Insert this directory so the shared, test-only
doubles in ``backend_fakes.py`` are importable across the test modules. The module is
uniquely named (not ``fakes``) to avoid colliding with the ML service's ``fakes.py``
under importlib import mode.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from backend.settings import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _pin_in_memory_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the in-memory rate limiter for every test so the suite never reads
    ``BE_RATE_LIMIT_IMPL`` from a developer's ``.env`` (pydantic-settings reads unset
    fields from it). A ``redis`` impl with an unreachable host (``redis://redis:…`` from
    the host) makes the limiter block on connect *and* fail open — which slows every
    ``create_app()`` request across the whole suite and breaks the 429 assertions. The
    real Redis limiter is covered directly by its gated adapter test, not the middleware."""
    monkeypatch.setattr(settings, "rate_limit_impl", "memory")
