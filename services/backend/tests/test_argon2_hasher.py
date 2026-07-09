"""The argon2 password hasher adapter (decisions/0024)."""

from __future__ import annotations

from backend.adapters.security.argon2_hasher import Argon2PasswordHasher


def test_hash_is_salted_and_verifies() -> None:
    hasher = Argon2PasswordHasher()
    hashed = hasher.hash("s3cret-pw")
    assert hashed != "s3cret-pw"
    assert hashed.startswith("$argon2")
    # Salted: two hashes of the same input differ, both verify.
    assert hasher.hash("s3cret-pw") != hashed
    assert hasher.verify("s3cret-pw", hashed) is True
    assert hasher.verify("wrong", hashed) is False


def test_malformed_stored_hash_fails_closed() -> None:
    hasher = Argon2PasswordHasher()
    # A garbage stored hash must return False, never raise (no 500 on bad data).
    assert hasher.verify("anything", "not-a-real-hash") is False
    assert hasher.needs_rehash("not-a-real-hash") is False


def test_fresh_hash_does_not_need_rehash() -> None:
    hasher = Argon2PasswordHasher()
    assert hasher.needs_rehash(hasher.hash("x")) is False
