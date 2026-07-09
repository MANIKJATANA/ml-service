"""HTTP ``MlEnrollmentClient`` — calls the ML enrollment API (decisions/0009).

The backend's only outbound call to the ML service. Enroll/refresh is synchronous
(the ML service fetches the reference photo, detects, embeds, upserts, and returns
per-photo results). Any transport failure or non-2xx response becomes an
``UpstreamError`` (→ 502) so the caller can record ``enrollment_status='failed'`` and
offer a retry. A fresh client per call keeps this free of event-loop lifecycle wiring;
enrollment is infrequent (per student create/delete).
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.domain.errors import UpstreamError
from backend.domain.models import EnrollmentOutcome, PhotoResult


class HttpMlEnrollmentClient:
    """``MlEnrollmentClient`` over httpx against ``base_url`` (the ML service)."""

    def __init__(self, base_url: str, *, timeout_s: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s

    def _enroll_url(self, school_id: str, student_id: str) -> str:
        return (
            f"{self._base_url}/v1/schools/{school_id}"
            f"/students/{student_id}/enroll"
        )

    def _student_url(self, school_id: str, student_id: str) -> str:
        return f"{self._base_url}/v1/schools/{school_id}/students/{student_id}"

    async def enroll(
        self, *, school_id: str, student_id: str, photo_uris: list[str]
    ) -> EnrollmentOutcome:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._enroll_url(school_id, student_id),
                    json={"photo_uris": photo_uris},
                )
                resp.raise_for_status()
                payload: Any = resp.json()
        except httpx.HTTPError as exc:
            raise UpstreamError(
                f"ML enroll failed for student {student_id}: {exc}"
            ) from exc
        return _to_outcome(payload)

    async def delete(self, *, school_id: str, student_id: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.delete(self._student_url(school_id, student_id))
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise UpstreamError(
                f"ML delete failed for student {student_id}: {exc}"
            ) from exc


def _to_outcome(payload: Any) -> EnrollmentOutcome:
    if not isinstance(payload, dict):
        raise UpstreamError(f"ML enroll returned a non-object body: {payload!r}")
    raw_results = payload.get("photo_results") or []
    try:
        results = tuple(
            PhotoResult(
                index=int(r.get("index", i)),
                status=str(r.get("status", "")),
                detail=r.get("detail"),
            )
            for i, r in enumerate(raw_results)
            if isinstance(r, dict)
        )
        embeddings_stored = int(payload.get("embeddings_stored", 0))
    except (TypeError, ValueError) as exc:  # malformed field types
        raise UpstreamError(f"ML enroll returned a malformed body: {payload!r}") from exc
    return EnrollmentOutcome(
        embeddings_stored=embeddings_stored, photo_results=results
    )
