"""In-proc ``MlEnrollmentClient`` — for offline dev/tests (decisions/0026).

Pairs with the ``local_fs`` object store so the backend runs with no Supabase and no
ML service. It reports a successful single-embedding enrollment (so the create flow
records ``enrolled``) and records delete calls. NOT a mock in the test-double sense —
it is a real, deterministic adapter selected by ``BE_ML_ENROLLMENT_CLIENT_IMPL=fake``.
"""

from __future__ import annotations

from backend.domain.models import EnrollmentOutcome, PhotoResult


class FakeMlEnrollmentClient:
    """Always-succeeds enrollment client for credential-free local dev."""

    async def enroll(
        self, *, school_id: str, student_id: str, photo_uris: list[str]
    ) -> EnrollmentOutcome:
        return EnrollmentOutcome(
            embeddings_stored=len(photo_uris),
            photo_results=tuple(
                PhotoResult(index=i, status="enrolled")
                for i in range(len(photo_uris))
            ),
        )

    async def delete(self, *, school_id: str, student_id: str) -> None:
        return None
