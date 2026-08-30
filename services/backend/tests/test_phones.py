"""Mobile-number normalization rule (Phase 0 — WhatsApp contact)."""

from __future__ import annotations

import pytest
from backend.domain.errors import ValidationError
from backend.domain.phones import validate_mobile


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        (" +12345678 ", "+12345678"),  # trimmed, keeps the leading '+'
        ("1234567", "1234567"),  # 7 digits — the lower bound
        ("123456789012345", "123456789012345"),  # 15 digits — the upper bound
        # A leading '+' does NOT count toward the digit run: '+' + 15 digits (16 chars) accepts.
        ("+123456789012345", "+123456789012345"),
    ],
)
def test_validate_mobile_accepts_optional_and_valid(
    raw: str | None, expected: str | None
) -> None:
    assert validate_mobile(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "123456",  # 6 digits — too short
        "1234567890123456",  # 16 digits — too long
        "+",  # no digits
        "12-34-567",  # separators not allowed
        "12 34567",  # inner whitespace not allowed
        "abc1234",  # letters
        "+12a4567",  # a stray letter
    ],
)
def test_validate_mobile_rejects_malformed(raw: str) -> None:
    with pytest.raises(ValidationError):
        validate_mobile(raw)
