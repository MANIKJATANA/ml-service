"""Postgres implementation of :class:`UserRepository` (decisions/0023)."""

from __future__ import annotations

from sqlalchemy import func, select
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

    async def delete(self, user_id: str) -> None:
        key = opt_uuid(user_id)
        if key is None:
            return  # malformed id -> nothing to delete (idempotent)
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(UserRow, key)
            if row is not None:
                await session.delete(row)

    async def count_by_school_and_role(self, school_id: str, role: Role) -> int:
        key = opt_uuid(school_id)
        if key is None:
            return 0  # malformed id -> no such tenant
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(func.count())
                .select_from(UserRow)
                .where(UserRow.school_id == key, UserRow.role == role.value)
            )
            return result.scalar_one()

    async def list_by_school_and_role(self, school_id: str, role: Role) -> list[User]:
        key = opt_uuid(school_id)
        if key is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(UserRow)
                .where(UserRow.school_id == key, UserRow.role == role.value)
                .order_by(UserRow.created_at, UserRow.id)  # stable when ties
            )
            return [_to_user(r) for r in result.scalars().all()]

    async def role_counts_by_school(self) -> dict[str, dict[Role, int]]:
        """Users grouped by (school, role) across all schools (BP2 platform rollup).

        One grouped scan (``ix_users_school_role``); platform admins (null school) are
        excluded. Cross-tenant on purpose (reachable only behind ``school:manage``).
        Keys are canonical UUID strings; inner keys are ``Role`` members."""
        counts: dict[str, dict[Role, int]] = {}
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(UserRow.school_id, UserRow.role, func.count())
                .where(UserRow.school_id.is_not(None))
                .group_by(UserRow.school_id, UserRow.role)
            )
            for school_id, role_value, n in result.all():
                counts.setdefault(str(school_id), {})[Role(role_value)] = n
        return counts
