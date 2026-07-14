"""Gallery + download API schemas (decisions/0028).

Gallery **list** items carry photo metadata only (no internal ``storage_path``); the FE
fetches bytes lazily via ``GET /media/{id}/download``, which mints a short-lived signed
URL — avoiding N signing round-trips to render one list.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from backend.domain.models import MatchVerdict, Media, MediaType, SignedDownload
from backend.services.gallery_service import (
    EventForStudent,
    MediaAppearance,
    StudentInEvent,
)

__all__ = [
    "DownloadResponse",
    "EventForStudentResponse",
    "GalleryMediaResponse",
    "MediaAppearanceResponse",
    "StudentInEventResponse",
]


class GalleryMediaResponse(BaseModel):
    """A photo in a gallery — metadata only; fetch bytes via the download endpoint."""

    media_id: str
    event_id: str
    media_type: MediaType

    @classmethod
    def from_media(cls, media: Media) -> GalleryMediaResponse:
        return cls(
            media_id=media.id,
            event_id=media.event_id,
            media_type=media.media_type,
        )


class StudentInEventResponse(BaseModel):
    """A student who appears in an event + how many of its photos they're in."""

    student_id: str
    name: str
    media_count: int

    @classmethod
    def from_view(cls, view: StudentInEvent) -> StudentInEventResponse:
        return cls(
            student_id=view.student.id,
            name=view.student.name,
            media_count=view.media_count,
        )


class EventForStudentResponse(BaseModel):
    """An event a student appears in + how many of its photos they're in."""

    event_id: str
    name: str
    event_date: date | None
    media_count: int

    @classmethod
    def from_view(cls, view: EventForStudent) -> EventForStudentResponse:
        return cls(
            event_id=view.event.id,
            name=view.event.name,
            event_date=view.event.event_date,
            media_count=view.media_count,
        )


class MediaAppearanceResponse(BaseModel):
    """A student who appears in one photo + that match's decision facts + the correction
    verdict (BP5). ``verdict`` null = an uncorrected ML match ("pending"); ``confidence``
    null = an ``added`` (staff-added) student with no ML score."""

    student_id: str
    name: str
    confidence: float | None
    needs_review: bool
    verdict: MatchVerdict | None

    @classmethod
    def from_view(cls, view: MediaAppearance) -> MediaAppearanceResponse:
        return cls(
            student_id=view.student.id,
            name=view.student.name,
            confidence=view.confidence,
            needs_review=view.needs_review,
            verdict=view.verdict,
        )


class DownloadResponse(BaseModel):
    """A short-lived signed URL to fetch one media."""

    download_url: str
    expires_in_s: int

    @classmethod
    def from_signed(cls, signed: SignedDownload) -> DownloadResponse:
        return cls(
            download_url=signed.download_url,
            expires_in_s=signed.expires_in_s,
        )
