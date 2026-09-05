"""Program analytics use-cases — the school + estate program views (BP14, decisions/0062).

Two reads, both composed purely from ports (no HTTP, no RBAC): authorization is at the
route (``dashboard:view`` for the school tier, ``school:manage`` for the estate tier), and
the school tier's tenant is the caller's token ``school_id`` — never the URL. Everything is
query-only over the backend's own rows plus the new ``last_login_at`` signal (migration
0016); the ML ``matches`` seam is never touched (no per-student rows, no cross-seam join).

``school_analytics`` turns the point-in-time counts into a program view: delivery / sign-in /
engagement rates, per-term rollups, and a month-by-month upload/event trend. ``estate_analytics``
lifts that to the platform tier — a per-school adoption funnel (staff → students → enrolled →
events → distributed) plus a transparent stalled/idle heuristic. Both compose grouped-count
queries in-Python (the BP1/BP2 pattern) — no N+1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from backend.domain.errors import NotFoundError
from backend.domain.models import EnrollmentStatus, Event, MatchVerdict, Role
from backend.domain.ports import (
    DownloadAuditRepository,
    EventRepository,
    MatchCorrectionRepository,
    MediaRepository,
    NotificationReadRepository,
    SchoolRepository,
    StudentRepository,
    UserRepository,
    WhatsAppSendLogRepository,
)

# A school with students but no event created in this window reads as "gone quiet" (idle).
# A transparent, tunable rule — not a scoring model (documented, decisions/0062).
_STALL_WINDOW_DAYS = 30
# The trend line is bounded to the most recent months so the payload/axis stays small.
_TREND_MONTHS = 12


@dataclass(frozen=True, slots=True)
class TermRollup:
    """Per-term rollup for the school analytics page — events, photos, and how many of the
    term's events were announced. Keyed by the free-text ``term`` (BP11b)."""

    term: str
    events: int
    photos: int
    distributed: int


@dataclass(frozen=True, slots=True)
class MonthPoint:
    """One point on the month-by-month trend (``month`` = ``'YYYY-MM'``). ``first_opens`` (BP23)
    is the count of student first-opens that month — an engagement line that *can* decline."""

    month: str
    photos: int
    events: int
    first_opens: int = 0


@dataclass(frozen=True, slots=True)
class QualityPoint:
    """One month of matching-quality ground truth (BP23 "Quality"). Raw verdict counts — the FE
    renders confirm-rate = ``confirmed / (confirmed + rejected)`` + a separate rejected rate;
    ``added`` (report-a-miss, a recall signal) is shown on its own, never in the precision
    denominator. Descriptive only — no model change (that stays parked BP15)."""

    month: str
    confirmed: int
    rejected: int
    added: int


@dataclass(frozen=True, slots=True)
class SchoolAnalytics:
    """A school's program view (BP14). Raw numerators + denominators — the FE renders the
    rates (delivery = distributed/events, sign-in = signed_in/students, engagement =
    engaged/students) so the percentage rounding lives in one place."""

    school_name: str
    students_total: int
    students_enrolled: int
    students_signed_in: int
    students_engaged: int  # distinct students who have opened >=1 distribution
    students_saved: int  # BP23: distinct students who saved >=1 of their own photos
    events_total: int
    events_distributed: int  # announced
    events_opened: int  # BP23: distinct announced events with >=1 opener (reach numerator)
    photos_total: int
    terms: tuple[TermRollup, ...]
    months: tuple[MonthPoint, ...]
    quality: tuple[QualityPoint, ...]  # BP23: monthly correction verdicts (matching quality)


@dataclass(frozen=True, slots=True)
class SchoolFunnel:
    """One school's adoption funnel for the estate view. ``stalled`` = the enrollment wall
    (students imported, none enrolled); ``idle`` = enrolled but no recent event activity.

    BP23 age axis: ``created_at`` (school age), ``not_started`` (no event created yet),
    ``days_to_first_delivery`` (signup → first announce, None if never), ``stalled_since``
    (the most recent event's time — "no event since …"; None if never created one)."""

    school_id: str
    school_name: str
    teachers: int
    students: int
    enrolled: int
    events: int
    distributed: int
    signed_in_students: int
    stalled: bool
    idle: bool
    created_at: datetime
    not_started: bool
    days_to_first_delivery: int | None
    stalled_since: datetime | None
    # WhatsApp cost: images actually SENT (each = one message). Total (all-time) + this UTC month.
    whatsapp_sent: int
    whatsapp_sent_month: int


@dataclass(frozen=True, slots=True)
class EstateAnalytics:
    """The platform-wide adoption view (BP14): every school's funnel + estate totals."""

    schools: tuple[SchoolFunnel, ...]
    total_schools: int
    total_students: int
    total_enrolled: int
    total_events: int
    stalled_schools: int
    idle_schools: int
    # WhatsApp cost across the estate: images sent all-time + this UTC month (the current bill).
    whatsapp_sent_total: int
    whatsapp_sent_month_total: int


def _announced(event: Event) -> bool:
    """BP4's event-level "announced" predicate (decisions/0041) — a manual push OR an
    auto-notify event that has completed. Mirrors ``EventRepository.count_distributed``."""
    return event.notified_at is not None or (
        event.auto_notify and event.completed_at is not None
    )


class AnalyticsService:
    def __init__(
        self,
        schools: SchoolRepository,
        users: UserRepository,
        students: StudentRepository,
        events: EventRepository,
        media: MediaRepository,
        reads: NotificationReadRepository,
        corrections: MatchCorrectionRepository,
        audit: DownloadAuditRepository,
        whatsapp_send_log: WhatsAppSendLogRepository,
    ) -> None:
        self._schools = schools
        self._users = users
        self._students = students
        self._events = events
        self._media = media
        self._reads = reads
        self._corrections = corrections
        self._audit = audit
        self._whatsapp_send_log = whatsapp_send_log

    async def school_analytics(self, *, school_id: str) -> SchoolAnalytics:
        school = await self._schools.get(school_id)
        if school is None:  # a valid token whose school was deleted — fail closed
            raise NotFoundError(f"school not found: {school_id}")

        enrollment = await self._students.enrollment_counts(school_id)
        signed_in = await self._users.count_signed_in_by_school_and_role(
            school_id, Role.STUDENT
        )
        engaged = await self._reads.count_distinct_seen_students(school_id)
        # BP23: the opened-event ids (reach) + distinct students who saved a photo.
        opened_event_ids = set(await self._reads.distinct_opened_event_ids(school_id))
        saved = await self._audit.count_distinct_saver_students(school_id)

        # Events + photos + per-term all derive from one events pass (bounded: ~120/yr) plus
        # the grouped photo-per-event scan — no separate status_counts/count_distributed
        # round-trips, and the announced predicate stays consistent with the estate tier.
        events = await self._events.list_by_school(school_id)
        photos_by_event = await self._media.counts_by_event(school_id)
        terms = _term_rollups(events, photos_by_event)
        announced_ids = {e.id for e in events if _announced(e)}
        events_distributed = len(announced_ids)
        # Reach = "of the currently-ANNOUNCED events, how many were opened" — the honest
        # intersection (in-Python, seam-free), so it never over-reports an event opened then
        # un-announced (auto_notify toggled off), and is a true floor bounded by events_distributed.
        events_opened = len(announced_ids & opened_event_ids)

        monthly_photos = await self._media.monthly_upload_counts(school_id)
        monthly_events = await self._events.monthly_event_date_counts(school_id)
        # BP23: first-opens trend (a decline-capable engagement line) + matching-quality verdicts.
        monthly_first_opens = await self._reads.monthly_first_open_counts(school_id)
        monthly_verdicts = await self._corrections.monthly_verdict_counts(school_id)
        months = _trend(monthly_photos, monthly_events, monthly_first_opens)
        quality = _quality(monthly_verdicts)

        return SchoolAnalytics(
            school_name=school.name,
            students_total=sum(enrollment.values()),
            students_enrolled=enrollment[EnrollmentStatus.ENROLLED],
            students_signed_in=signed_in,
            students_engaged=engaged,
            students_saved=saved,
            events_total=len(events),
            events_distributed=events_distributed,
            events_opened=events_opened,
            photos_total=sum(photos_by_event.values()),
            terms=terms,
            months=months,
            quality=quality,
        )

    async def estate_analytics(self) -> EstateAnalytics:
        schools = await self._schools.list_all()
        role_counts = await self._users.role_counts_by_school()
        signed_in = await self._users.signed_in_role_counts_by_school()
        students_by = await self._students.counts_by_school()
        enrolled_by = await self._students.enrolled_counts_by_school()
        events_by = await self._events.counts_by_school()
        distributed_by = await self._events.distributed_counts_by_school()
        since = datetime.now(UTC) - timedelta(days=_STALL_WINDOW_DAYS)
        recent_by = await self._events.recent_event_counts_by_school(since)
        # BP23 age axis: first-announce time (days-to-first-delivery) + last-event time (idle).
        first_distributed_by = await self._events.first_distributed_at_by_school()
        last_event_by = await self._events.last_event_created_at_by_school()
        # WhatsApp cost: images sent per school, all-time + this UTC month (the current bill).
        now = datetime.now(UTC)
        month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
        wa_sent_by = await self._whatsapp_send_log.sent_counts_by_school()
        wa_sent_month_by = await self._whatsapp_send_log.sent_counts_by_school(
            since=month_start
        )

        funnels: list[SchoolFunnel] = []
        for s in schools:
            students = students_by.get(s.id, 0)
            enrolled = enrolled_by.get(s.id, 0)
            recent = recent_by.get(s.id, 0)
            events = events_by.get(s.id, 0)
            # The enrollment wall: students imported, none enrolled → can't be turned on.
            stalled = students > 0 and enrolled == 0
            # Past the wall but gone quiet: enrolled students, no recent event.
            idle = not stalled and enrolled > 0 and recent == 0
            first_dist = first_distributed_by.get(s.id)
            days_to_first = (
                max(0, (first_dist - s.created_at).days)
                if first_dist is not None
                else None
            )
            funnels.append(
                SchoolFunnel(
                    school_id=s.id,
                    school_name=s.name,
                    teachers=role_counts.get(s.id, {}).get(Role.TEACHER, 0),
                    students=students,
                    enrolled=enrolled,
                    events=events,
                    distributed=distributed_by.get(s.id, 0),
                    signed_in_students=signed_in.get(s.id, {}).get(Role.STUDENT, 0),
                    stalled=stalled,
                    idle=idle,
                    created_at=s.created_at,
                    not_started=events == 0,
                    days_to_first_delivery=days_to_first,
                    stalled_since=last_event_by.get(s.id),
                    whatsapp_sent=wa_sent_by.get(s.id, 0),
                    whatsapp_sent_month=wa_sent_month_by.get(s.id, 0),
                )
            )

        return EstateAnalytics(
            schools=tuple(funnels),
            total_schools=len(schools),
            total_students=sum(students_by.values()),
            total_enrolled=sum(enrolled_by.values()),
            total_events=sum(events_by.values()),
            stalled_schools=sum(1 for f in funnels if f.stalled),
            idle_schools=sum(1 for f in funnels if f.idle),
            # Estate-wide WhatsApp cost (sum the per-school counts; a school with no sends is absent
            # from the dict → contributes 0).
            whatsapp_sent_total=sum(wa_sent_by.values()),
            whatsapp_sent_month_total=sum(wa_sent_month_by.values()),
        )


def _term_rollups(
    events: list[Event], photos_by_event: dict[str, int]
) -> tuple[TermRollup, ...]:
    """Group events by their (non-null) ``term`` into event/photo/announced counts, sorted
    by term name. Untagged events are omitted (they belong to no term)."""
    agg: dict[str, list[int]] = {}
    for e in events:
        # A blank/whitespace term (BP11b stores term free-text with no min-length) is treated
        # as untagged here — never a blank rollup chip.
        if e.term is None or not e.term.strip():
            continue
        row = agg.setdefault(e.term, [0, 0, 0])
        row[0] += 1
        row[1] += photos_by_event.get(e.id, 0)
        if _announced(e):
            row[2] += 1
    return tuple(
        TermRollup(term=t, events=r[0], photos=r[1], distributed=r[2])
        for t, r in sorted(agg.items())
    )


def _trend(
    photos: dict[str, int],
    events: dict[str, int],
    first_opens: dict[str, int],
) -> tuple[MonthPoint, ...]:
    """Merge the per-month photo + event + first-open counts into a sorted trend, keeping the
    most recent ``_TREND_MONTHS`` months (each key is a sortable ``'YYYY-MM'``)."""
    months = sorted(set(photos) | set(events) | set(first_opens))[-_TREND_MONTHS:]
    return tuple(
        MonthPoint(
            month=m,
            photos=photos.get(m, 0),
            events=events.get(m, 0),
            first_opens=first_opens.get(m, 0),
        )
        for m in months
    )


def _quality(
    monthly_verdicts: dict[str, dict[MatchVerdict, int]],
) -> tuple[QualityPoint, ...]:
    """Fold the grouped month × verdict counts into a sorted quality trend (most recent
    ``_TREND_MONTHS`` months). Raw counts — the FE computes the confirm/reject rates."""
    months = sorted(monthly_verdicts)[-_TREND_MONTHS:]
    return tuple(
        QualityPoint(
            month=m,
            confirmed=monthly_verdicts[m].get(MatchVerdict.CONFIRMED, 0),
            rejected=monthly_verdicts[m].get(MatchVerdict.REJECTED, 0),
            added=monthly_verdicts[m].get(MatchVerdict.ADDED, 0),
        )
        for m in months
    )
