"""Argon2 password hasher (passlib) — the only place password crypto is imported.

Implements the `PasswordHasher` port (decisions/0024). passlib's `CryptContext`
handles salting, the argon2id variant, and parameter upgrades (`needs_rehash`), so
the service layer never touches a crypto primitive.
"""

from __future__ import annotations

from passlib.context import CryptContext


class Argon2PasswordHasher:
    def __init__(self) -> None:
        # deprecated="auto" makes needs_update() report when the default argon2
        # parameters have moved on, so login can transparently re-hash.
        self._ctx = CryptContext(schemes=["argon2"], deprecated="auto")

    def hash(self, plaintext: str) -> str:
        # passlib is untyped (Any) — coerce explicitly for the strict boundary.
        return str(self._ctx.hash(plaintext))

    def verify(self, plaintext: str, hashed: str) -> bool:
        # Any malformed/unknown stored hash must fail closed (return False), never
        # bubble a 500 — passlib raises several exception types (UnknownHashError,
        # TypeError, backend-specific) for bad input, so catch broadly (0024).
        try:
            return bool(self._ctx.verify(plaintext, hashed))
        except Exception:
            return False

    def needs_rehash(self, hashed: str) -> bool:
        try:
            return bool(self._ctx.needs_update(hashed))
        except Exception:
            return False
