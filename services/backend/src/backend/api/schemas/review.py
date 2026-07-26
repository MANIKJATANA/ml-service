"""Match-review (trust & accuracy) API schemas (BP5, decisions/0042)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.domain.models import MediaType
from backend.services.review_service import MediaReview

__all__ = [
    "AddMissedRequest",
    "BatchReviewRequest",
    "BatchReviewResponse",
    "MediaReviewResponse",
    "SetVerdictRequest",
]

# The most verdicts one batch call can carry — well above a huge event's review lane; over it
# is a 422 (an abuse ceiling, not a real limit).
_MAX_BATCH = 2000


class SetVerdictRequest(BaseModel):
    """Confirm or reject an ML match (staff). 'added' is the separate report-a-miss route."""

    verdict: Literal["confirmed", "rejected"]


class BatchVerdictItem(BaseModel):
    """One (media, student) decision in a batch (BP13)."""

    media_id: str = Field(min_length=1)
    student_id: str = Field(min_length=1)
    verdict: Literal["confirmed", "rejected"]


class BatchReviewRequest(BaseModel):
    """Apply many confirm/reject verdicts over one event's review lane at once (BP13). A pair
    that isn't a real match in the event is silently skipped in the service (tenant-safe)."""

    verdicts: list[BatchVerdictItem] = Field(min_length=1, max_length=_MAX_BATCH)


class BatchReviewResponse(BaseModel):
    applied: int


class AddMissedRequest(BaseModel):
    """Report-a-miss: add a student the ML missed to this photo."""

    student_id: str = Field(min_length=1)


class ReviewCandidateResponse(BaseModel):
    student_id: str
    name: str
    confidence: float


class MediaReviewResponse(BaseModel):
    """One photo with its ambiguous, unresolved matches — the staff review lane."""

    media_id: str
    event_id: str
    media_type: MediaType
    candidates: list[ReviewCandidateResponse]

    @classmethod
    def from_view(cls, view: MediaReview) -> MediaReviewResponse:
        return cls(
            media_id=view.media.id,
            event_id=view.media.event_id,
            media_type=view.media.media_type,
            candidates=[
                ReviewCandidateResponse(
                    student_id=c.student.id, name=c.student.name, confidence=c.confidence
                )
                for c in view.candidates
            ],
        )
