"""Postgres ``ReferencePhotoRepository`` — stores a student's reference-photo
URIs (decisions/0009). Backs student-id-triggered enrollment: ``EnrollmentService``
reads URIs through this port and fetches the bytes via ``MediaStore``.

``replace`` is a delete-then-insert in one transaction so ordering (``position``)
is rebuilt cleanly and the operation is atomic.
"""

from __future__ import annotations

from sqlalchemy import Delete, delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ml_service.db.models import StudentReferencePhoto


class PostgresReferencePhotoRepository:
    """Reads/replaces/deletes a student's reference-photo URIs."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def get(self, school_id: str, student_id: str) -> list[str]:
        stmt = (
            select(StudentReferencePhoto.photo_uri)
            .where(
                StudentReferencePhoto.school_id == school_id,
                StudentReferencePhoto.student_id == student_id,
            )
            .order_by(StudentReferencePhoto.position)
        )
        async with self._sessionmaker() as session:
            result = await session.execute(stmt)
            return [row[0] for row in result.all()]

    async def replace(
        self, school_id: str, student_id: str, photo_uris: list[str]
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(self._delete_stmt(school_id, student_id))
            if photo_uris:
                await session.execute(
                    insert(StudentReferencePhoto),
                    [
                        {
                            "school_id": school_id,
                            "student_id": student_id,
                            "photo_uri": uri,
                            "position": i,
                        }
                        for i, uri in enumerate(photo_uris)
                    ],
                )

    async def delete(self, school_id: str, student_id: str) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(self._delete_stmt(school_id, student_id))

    @staticmethod
    def _delete_stmt(school_id: str, student_id: str) -> Delete:
        return delete(StudentReferencePhoto).where(
            StudentReferencePhoto.school_id == school_id,
            StudentReferencePhoto.student_id == student_id,
        )
