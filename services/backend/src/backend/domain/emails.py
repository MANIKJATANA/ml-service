"""Email normalization — the rule that makes email a case-insensitive identifier.

Pure (no third-party imports). Emails are compared/stored normalized so a user who
registered as ``Ops@X.io`` can log in as ``ops@x.io`` and ``uq_users_email`` rejects
case-variant duplicates (decisions/0023 deferred this to Phase 2 / 0024). Applied at
the persistence boundary (the user repository) so every read and write agree,
regardless of caller. v1 lower-cases the whole address; a citext column preserving
display case is the documented scale-up.
"""

from __future__ import annotations


def normalize_email(email: str) -> str:
    return email.strip().lower()
