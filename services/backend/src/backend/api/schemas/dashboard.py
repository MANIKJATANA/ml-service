"""Admin dashboard API schema (BP1, decisions/0038).

One nested response for the school command center: student/event/photo rollups plus a
``needs_attention`` block of the two-or-three "do something" signals. All counts are read
live from the backend's own rows (and the ML ``matches`` seam) — no stored aggregate.
"""

from __future__ import annotations

from pydantic import BaseModel

from backend.services.dashboard_service import SchoolDashboard

__all__ = ["DashboardResponse"]


class StudentsSummary(BaseModel):
    total: int
    enrolled: int
    pending: int
    failed: int


class EventsSummary(BaseModel):
    total: int
    active: int
    archived: int
    processing: int


class MediaSummary(BaseModel):
    total: int
    pending: int


class NeedsAttention(BaseModel):
    """The dashboard's "do something" signals — each renders as an actionable alert."""

    events_undistributed: int  # have photos but Process was never pressed
    enrollment_failures: int  # students whose ML enrollment failed
    needs_review: int  # ambiguous matches staff may want to triage


class DashboardResponse(BaseModel):
    school_name: str
    students: StudentsSummary
    events: EventsSummary
    media: MediaSummary
    needs_attention: NeedsAttention

    @classmethod
    def from_dashboard(cls, d: SchoolDashboard) -> DashboardResponse:
        return cls(
            school_name=d.school_name,
            students=StudentsSummary(
                total=d.students_total,
                enrolled=d.students_enrolled,
                pending=d.students_pending,
                failed=d.students_failed,
            ),
            events=EventsSummary(
                total=d.events_total,
                active=d.events_active,
                archived=d.events_archived,
                processing=d.events_processing,
            ),
            media=MediaSummary(total=d.photos_total, pending=d.photos_pending),
            needs_attention=NeedsAttention(
                events_undistributed=d.events_undistributed,
                enrollment_failures=d.students_failed,
                needs_review=d.needs_review,
            ),
        )
