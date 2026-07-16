"""Email normalization — the rule that makes email a case-insensitive identifier.

Pure (no third-party imports). Emails are compared/stored normalized so a user who
registered as ``Ops@X.io`` can log in as ``ops@x.io`` and ``uq_users_email`` rejects
case-variant duplicates (decisions/0023 deferred this to Phase 2 / 0024). Applied at
the persistence boundary (the user repository) so every read and write agree,
regardless of caller. v1 lower-cases the whole address; a citext column preserving
display case is the documented scale-up.
"""

from __future__ import annotations

import re

from backend.domain.errors import ValidationError

# A pragmatic email check — not full RFC 5322, but rejects the obvious invalids (missing
# @, whitespace, no domain dot). The real uniqueness guard stays ``uq_users_email``; single
# create uses pydantic ``EmailStr`` at the edge. Used by bulk import, where per-row
# validation must NOT reject the whole batch.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_email(email: str) -> str:
    """Normalize + minimally validate an email; raise ``ValidationError`` on an obviously
    malformed one (BP7d bulk import). Returns the normalized address on success."""
    normalized = normalize_email(email)
    if not _EMAIL_RE.match(normalized):
        raise ValidationError(f"invalid email: {email!r}")
    return normalized
