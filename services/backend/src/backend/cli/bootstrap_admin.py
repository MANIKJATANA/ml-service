"""Bootstrap the first platform admin (decisions/0024).

    python -m backend.cli.bootstrap_admin --email ops@example.com

The password is read via ``getpass`` when ``--password`` is omitted, so it need
never appear in shell history or a process listing — and it is **never** read from
``.env`` (working rules; 0022 baked default). Assumes the backend DB is already
migrated (``alembic upgrade head``). Idempotent: a duplicate email is a reported
no-op.

Requires ``BE_DATABASE_URL`` in the environment (the DSN with the password). Needs no
JWT secret — it only touches the password hasher and the user repository.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from backend.domain.models import Role
from backend.settings import settings
from backend.wiring.container import Container

_MIN_PASSWORD_LEN = 8


async def _create(email: str, password: str) -> int:
    container = Container(settings)
    try:
        users = container.user_repo()
        if await users.get_by_email(email) is not None:
            print(f"platform admin already exists: {email}")
            return 0
        password_hash = container.password_hasher().hash(password)
        user = await users.create(
            school_id=None,
            email=email,
            password_hash=password_hash,
            role=Role.PLATFORM_ADMIN,
        )
        print(f"created platform admin {user.email} (id={user.id})")
        return 0
    finally:
        await container.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="backend.cli.bootstrap_admin",
        description="Create the first platform admin account.",
    )
    parser.add_argument("--email", required=True, help="platform admin email")
    parser.add_argument(
        "--password",
        default=None,
        help="password (omit to be prompted securely via getpass)",
    )
    args = parser.parse_args(argv)

    password = args.password or getpass.getpass("Password: ")
    if len(password) < _MIN_PASSWORD_LEN:
        print(
            f"password must be at least {_MIN_PASSWORD_LEN} characters",
            file=sys.stderr,
        )
        return 2

    return asyncio.run(_create(args.email, password))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
