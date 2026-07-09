"""Postgres implementation of :class:`UserRepository` (decisions/0023)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import opt_uuid, req_uuid, violated_constraint
from backend.db.models import User as UserRow
from backend.domain.emails import normalize_email
from backend.domain.errors import ConflictError, NotFoundError
from backend.domain.models import Role, User, UserStatus


def _to_user(row: UserRow) -> User:
    return User(
        id=str(row.id),
        school_id=str(row.school_id) if row.school_id is not None else None,
        email=row.email,
        password_hash=row.password_hash,
        role=Role(row.role),
        status=UserStatus(row.status),
        must_change_password=row.must_change_password,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PostgresUserRepository:
    """``UserRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(
        self,
        *,
        school_id: str | None,
        email: str,
        password_hash: str,
        role: Role,
        must_change_password: bool = False,
    ) -> User:
        sid = req_uuid(school_id, field="school_id") if school_id is not None else None
        async with self._sessionmaker() as session, session.begin():
            row = UserRow(
                school_id=sid,
                email=normalize_email(email),
                password_hash=password_hash,
                role=role.value,
                must_change_password=must_change_password,
            )
            session.add(row)
            try:
                await session.flush()
            except IntegrityError as exc:
                if violated_constraint(exc) == "uq_users_email":
                    raise ConflictError(f"email already registered: {email}") from exc
                raise  # FK / CHECK / not-null: a bad input, not an email conflict
            await session.refresh(row)
            return _to_user(row)

    async def get(self, user_id: str) -> User | None:
        key = opt_uuid(user_id)
        if key is None:
            return None
        async with self._sessionmaker() as session:
            row = await session.get(UserRow, key)
            return _to_user(row) if row is not None else None

    async def get_by_email(self, email: str) -> User | None:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(UserRow).where(UserRow.email == normalize_email(email))
            )
            row = result.scalar_one_or_none()
            return _to_user(row) if row is not None else None

    async def set_password(
        self, user_id: str, *, password_hash: str, must_change_password: bool
    ) -> None:
        key = req_uuid(user_id, field="user_id")
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(UserRow, key)
            if row is None:
                raise NotFoundError(f"user not found: {user_id}")
            # ORM mutation → flush on commit; also trips updated_at's onupdate.
            row.password_hash = password_hash
            row.must_change_password = must_change_password
