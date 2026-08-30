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
    failed: int = 0  # BP19c: photos the worker couldn't process


class StaffSummary(BaseModel):
    """Teacher-seat usage (A15) — surfaced on the staff page so an admin sees the cap
    before the create 409. ``teacher_count`` is status-agnostic (active + disabled)."""

    teacher_count: int
    max_teachers: int


class NeedsAttention(BaseModel):
    """The dashboard's "do something" signals — each renders as an actionable alert."""

    events_undistributed: int  # active events with photos still to process (BP19c: + 2nd batch)
    enrollment_failures: int  # students whose ML enrollment failed
    needs_review: int  # ambiguous matches staff may want to triage
    photos_failed: int = 0  # BP19c: photos that failed processing (was hidden by "All processed")


class SetupChecklist(BaseModel):
    """First-run onboarding progress (BP7a, decisions/0044) — the five steps to first
    value, each a done/not-done boolean the FE renders as a checklist that guides a fresh
    school and disappears once every step is complete. Composed server-side so "done"
    means the same thing everywhere: ``enrolled`` requires a *successful* enrollment (a
    student merely added but still pending/failed does NOT tick it)."""

    has_staff: bool  # >=1 teacher added
    has_enrolled_student: bool  # >=1 student whose ML enrollment succeeded
    has_event: bool  # >=1 event created
    has_media: bool  # >=1 photo/video uploaded
    has_distributed: bool  # >=1 event announced to students


class DashboardResponse(BaseModel):
    school_name: str
    students: StudentsSummary
    events: EventsSummary
    media: MediaSummary
    staff: StaffSummary
    setup_checklist: SetupChecklist
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
            media=MediaSummary(
                total=d.photos_total, pending=d.photos_pending, failed=d.photos_failed
            ),
            staff=StaffSummary(
                teacher_count=d.teacher_count, max_teachers=d.max_teachers
            ),
            setup_checklist=SetupChecklist(
                has_staff=d.has_staff,
                has_enrolled_student=d.students_enrolled > 0,
                has_event=d.events_total > 0,
                has_media=d.photos_total > 0,
                has_distributed=d.has_distributed,
            ),
            needs_attention=NeedsAttention(
                events_undistributed=d.events_undistributed,
                enrollment_failures=d.students_failed,
                needs_review=d.needs_review,
                photos_failed=d.photos_failed,
            ),
        )
