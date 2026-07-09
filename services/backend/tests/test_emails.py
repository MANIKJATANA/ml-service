"""Email normalization rule (decisions/0024)."""

from __future__ import annotations

from backend.domain.emails import normalize_email


def test_normalize_lowercases_and_strips() -> None:
    assert normalize_email("  Ops@X.IO ") == "ops@x.io"
    assert normalize_email("Already@lower.io") == "already@lower.io"
    assert normalize_email("a@b.com") == "a@b.com"
