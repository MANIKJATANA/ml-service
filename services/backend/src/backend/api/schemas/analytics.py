"""Program analytics API schemas (BP14, decisions/0062).

Two read responses: the school program view (rates as numerator/denominator + per-term
rollups + a monthly trend) and the platform estate view (per-school adoption funnel +
stalled/idle flags + estate totals). Raw counts flow to the FE, which renders the rates —
so the percentage rounding lives in one place.
"""

from __future__ import annotations

from pydantic import BaseModel

from backend.services.analytics_service import (
    EstateAnalytics,
    SchoolAnalytics,
)

__all__ = ["SchoolAnalyticsResponse", "EstateAnalyticsResponse"]


class TermRollupResponse(BaseModel):
    term: str
    events: int
    photos: int
    distributed: int


class MonthPointResponse(BaseModel):
    month: str  # 'YYYY-MM'
    photos: int
    events: int


class SchoolAnalyticsResponse(BaseModel):
    school_name: str
    students_total: int
    students_enrolled: int
    students_signed_in: int
    students_engaged: int
    events_total: int
    events_distributed: int
    photos_total: int
    terms: list[TermRollupResponse]
    months: list[MonthPointResponse]

    @classmethod
    def from_analytics(cls, a: SchoolAnalytics) -> SchoolAnalyticsResponse:
        return cls(
            school_name=a.school_name,
            students_total=a.students_total,
            students_enrolled=a.students_enrolled,
            students_signed_in=a.students_signed_in,
            students_engaged=a.students_engaged,
            events_total=a.events_total,
            events_distributed=a.events_distributed,
            photos_total=a.photos_total,
            terms=[
                TermRollupResponse(
                    term=t.term,
                    events=t.events,
                    photos=t.photos,
                    distributed=t.distributed,
                )
                for t in a.terms
            ],
            months=[
                MonthPointResponse(month=m.month, photos=m.photos, events=m.events)
                for m in a.months
            ],
        )


class SchoolFunnelResponse(BaseModel):
    school_id: str
    school_name: str
    teachers: int
    students: int
    enrolled: int
    events: int
    distributed: int
    signed_in_students: int
    stalled: bool  # the enrollment wall: students imported, none enrolled
    idle: bool  # enrolled but no event created in the recent window


class EstateAnalyticsResponse(BaseModel):
    schools: list[SchoolFunnelResponse]
    total_schools: int
    total_students: int
    total_enrolled: int
    total_events: int
    stalled_schools: int
    idle_schools: int

    @classmethod
    def from_analytics(cls, a: EstateAnalytics) -> EstateAnalyticsResponse:
        return cls(
            schools=[
                SchoolFunnelResponse(
                    school_id=f.school_id,
                    school_name=f.school_name,
                    teachers=f.teachers,
                    students=f.students,
                    enrolled=f.enrolled,
                    events=f.events,
                    distributed=f.distributed,
                    signed_in_students=f.signed_in_students,
                    stalled=f.stalled,
                    idle=f.idle,
                )
                for f in a.schools
            ],
            total_schools=a.total_schools,
            total_students=a.total_students,
            total_enrolled=a.total_enrolled,
            total_events=a.total_events,
            stalled_schools=a.stalled_schools,
            idle_schools=a.idle_schools,
        )
