"""Shared credential helpers (BP7c/BP7d).

A server-generated temp password used by the staff/admin invite model (onboarding) and by
student provisioning (single + bulk). Kept in one place so both services generate the same
kind of one-time password (shown once, then only its hash is stored).
"""

from __future__ import annotations

import secrets

# token_urlsafe(12) -> a 16-char URL-safe password: comfortably over the 8-char policy
# floor and easy to copy / read aloud.
_TEMP_PASSWORD_BYTES = 12


def generate_temp_password() -> str:
    """A CSPRNG URL-safe temp password — generated server-side, shown to the admin once,
    then only its hash is persisted."""
    return secrets.token_urlsafe(_TEMP_PASSWORD_BYTES)
