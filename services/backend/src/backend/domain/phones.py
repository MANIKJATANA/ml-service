"""Mobile-number normalization — the loose, optional contact rule for WhatsApp (Phase 0).

Pure (no third-party imports). A student's mobile number is optional (NULL when unknown) and
only loosely validated here: we trim, treat blank as absent (NULL), and accept an optional
leading ``+`` followed by 7–15 digits. This is a pragmatic gate, not authoritative E.164
parsing — the messaging provider validates the number authoritatively at send time. Applied at
the service boundary (like ``domain.emails.validate_email``), so single create, bulk import, and
the dedicated mobile edit all agree regardless of caller.
"""

from __future__ import annotations

import re

from backend.domain.errors import ValidationError

# Optional leading '+', then 7–15 digits. Loose on purpose (see the module docstring): the
# provider validates authoritatively at send time. Used by single create, bulk import, and the
# mobile edit, where a malformed value must surface as a per-caller/per-row error.
_MOBILE_RE = re.compile(r"^\+?[0-9]{7,15}$")


def validate_mobile(mobile: str | None) -> str | None:
    """Normalize + minimally validate an optional mobile number.

    Returns None for None/blank (mobile is optional → stored as NULL); otherwise trims and
    checks the loose pattern, raising ``ValidationError`` on a malformed value.
    """
    if mobile is None:
        return None
    trimmed = mobile.strip()
    if not trimmed:
        return None
    if not _MOBILE_RE.match(trimmed):
        raise ValidationError(f"invalid mobile number: {mobile!r}")
    return trimmed
