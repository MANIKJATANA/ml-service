"""NotificationService use-cases with fakes (BP4, decisions/0041).

Covers the derived "announced/unseen" logic (auto vs manual, re-notify resurfacing), the
manual notify fan-out + validations, mark-seen, and the staff roster; plus the
CompositeNotifier's best-effort channel isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from backend.adapters.notification.composite import CompositeNotifier
from backend.domain.errors import NotFoundError, ValidationError
from backend.domain.models import (
    Appearance,
    Event,
    EventProcessingStatus,
    EventStatus,
    Student,
)
from backend.services.notification_service import NotificationService
from backend_fakes import (
    FakeEventRepo,
    FakeMlResultsReader,
    FakeNotificationChannel,
    FakeNotificationReadRepo,
    FakeStudentRepo,
    make_appearance,
    make_event,
    make_student,
)

_S1 = "s1"
_T0 = datetime(2026, 6, 1, tzinfo=UTC)
_T1 = datetime(2026, 6, 2, tzinfo=UTC)


def _svc(
    *,
    events: list[Event] | None = None,
    students: list[Student] | None = None,
    appearances: list[Appearance] | None = None,
    reads: FakeNotificationReadRepo | None = None,
    notifier: FakeNotificationChannel | None = None,
) -> NotificationService:
    return NotificationService(
        FakeEventRepo(events or []),
        FakeMlResultsReader(appearances or []),
        FakeStudentRepo(students or []),
        reads or FakeNotificationReadRepo(),
        notifier or FakeNotificationChannel(),
    )


# ---- manual notify -----------------------------------------------------


async def test_notify_event_fans_out_to_matched_students_and_stamps() -> None:
    events = FakeEventRepo(
        [make_event(id="e1", school_id=_S1, completed_at=_T0)]
    )
    notifier = FakeNotificationChannel()
    svc = NotificationService(
        events,
        FakeMlResultsReader(
            [
                make_appearance(student_id="a", media_id="m1", event_id="e1"),
                make_appearance(student_id="a", media_id="m2", event_id="e1"),
                make_appearance(student_id="b", media_id="m1", event_id="e1"),
            ]
        ),
        FakeStudentRepo(
            [
                make_student(id="a", school_id=_S1, user_id="ua", name="Ann"),
                make_student(id="b", school_id=_S1, user_id="ub", name="Bob"),
                make_student(id="c", school_id=_S1, user_id="uc"),  # not matched
            ]
        ),
        FakeNotificationReadRepo(),
        notifier,
    )

    count = await svc.notify_event(school_id=_S1, event_id="e1")

    assert count == 2  # a, b — not c
    assert {n.student_id for n in notifier.sent} == {"a", "b"}
    assert {n.media_count for n in notifier.sent} == {2, 1}
    event = await events.get(_S1, "e1")
    assert event is not None and event.notified_at is not None  # stamped


async def test_notify_event_rejects_archived_and_unfinished() -> None:
    archived = _svc(
        events=[
            make_event(id="e1", school_id=_S1, status=EventStatus.ARCHIVED,
                       completed_at=_T0)
        ]
    )
    with pytest.raises(ValidationError):
        await archived.notify_event(school_id=_S1, event_id="e1")

    not_done = _svc(
        events=[
            make_event(id="e1", school_id=_S1,
                       processing_status=EventProcessingStatus.PROCESSING,
                       completed_at=None)
        ]
    )
    with pytest.raises(ValidationError):
        await not_done.notify_event(school_id=_S1, event_id="e1")


async def test_notify_missing_event_raises() -> None:
    with pytest.raises(NotFoundError):
        await _svc().notify_event(school_id=_S1, event_id="nope")


async def test_notify_event_with_no_matched_students_returns_zero() -> None:
    events = FakeEventRepo([make_event(id="e1", school_id=_S1, completed_at=_T0)])
    svc = NotificationService(
        events,
        FakeMlResultsReader([]),  # nobody matched
        FakeStudentRepo([make_student(id="a", school_id=_S1, user_id="ua")]),
        FakeNotificationReadRepo(),
        FakeNotificationChannel(),
    )
    assert await svc.notify_event(school_id=_S1, event_id="e1") == 0
    event = await events.get(_S1, "e1")
    assert event is not None and event.notified_at is not None  # still stamped announced


# ---- derived student signal --------------------------------------------


async def test_auto_completed_event_is_announced_and_unseen() -> None:
    svc = _svc(
        events=[make_event(id="e1", school_id=_S1, auto_notify=True, completed_at=_T0)],
        students=[make_student(id="st1", school_id=_S1, user_id="u1")],
        appearances=[make_appearance(student_id="st1", media_id="m1", event_id="e1")],
    )
    views = await svc.student_notifications(school_id=_S1, student_id="st1")
    assert len(views) == 1
    assert views[0].event.id == "e1"
    assert views[0].media_count == 1
    assert views[0].unseen is True


async def test_auto_off_and_not_notified_is_not_announced() -> None:
    svc = _svc(
        events=[make_event(id="e1", school_id=_S1, auto_notify=False, completed_at=_T0)],
        students=[make_student(id="st1", school_id=_S1, user_id="u1")],
        appearances=[make_appearance(student_id="st1", media_id="m1", event_id="e1")],
    )
    assert await svc.student_notifications(school_id=_S1, student_id="st1") == []


async def test_announced_event_stays_visible_after_archive() -> None:
    # A student keeps photos already announced to them even if staff later archive the event.
    svc = _svc(
        events=[
            make_event(id="e1", school_id=_S1, status=EventStatus.ARCHIVED,
                       auto_notify=True, completed_at=_T0)
        ],
        students=[make_student(id="st1", school_id=_S1, user_id="u1")],
        appearances=[make_appearance(student_id="st1", media_id="m1", event_id="e1")],
    )
    views = await svc.student_notifications(school_id=_S1, student_id="st1")
    assert len(views) == 1


async def test_manual_notify_announces_even_with_auto_off() -> None:
    svc = _svc(
        events=[
            make_event(id="e1", school_id=_S1, auto_notify=False, completed_at=_T0,
                       notified_at=_T1)
        ],
        students=[make_student(id="st1", school_id=_S1, user_id="u1")],
        appearances=[make_appearance(student_id="st1", media_id="m1", event_id="e1")],
    )
    views = await svc.student_notifications(school_id=_S1, student_id="st1")
    assert len(views) == 1 and views[0].unseen is True


async def test_seen_clears_then_renotify_resurfaces() -> None:
    reads = FakeNotificationReadRepo()
    reads.set_seen("st1", "e1", _T0)  # student opened it at T0
    svc = _svc(
        events=[make_event(id="e1", school_id=_S1, auto_notify=True, completed_at=_T0)],
        students=[make_student(id="st1", school_id=_S1, user_id="u1")],
        appearances=[make_appearance(student_id="st1", media_id="m1", event_id="e1")],
        reads=reads,
    )
    # Announced at T0, seen at T0 -> seen.
    views = await svc.student_notifications(school_id=_S1, student_id="st1")
    assert views[0].unseen is False

    # Staff re-notify at T1 (> the T0 read) -> resurfaces as unseen.
    resurfaced = _svc(
        events=[
            make_event(id="e1", school_id=_S1, auto_notify=True, completed_at=_T0,
                       notified_at=_T1)
        ],
        students=[make_student(id="st1", school_id=_S1, user_id="u1")],
        appearances=[make_appearance(student_id="st1", media_id="m1", event_id="e1")],
        reads=reads,
    )
    views2 = await resurfaced.student_notifications(school_id=_S1, student_id="st1")
    assert views2[0].unseen is True


async def test_mark_seen_upserts_and_requires_event() -> None:
    reads = FakeNotificationReadRepo()
    svc = _svc(
        events=[make_event(id="e1", school_id=_S1, completed_at=_T0)],
        reads=reads,
    )
    await svc.mark_seen(school_id=_S1, student_id="st1", event_id="e1")
    assert (await reads.list_for_student(_S1, "st1")) != {}
    with pytest.raises(NotFoundError):
        await svc.mark_seen(school_id=_S1, student_id="st1", event_id="nope")


# ---- staff roster ------------------------------------------------------


async def test_event_roster_reports_matched_and_seen() -> None:
    reads = FakeNotificationReadRepo()
    reads.set_seen("a", "e1", _T1)  # Ann opened it after the announce
    svc = _svc(
        events=[make_event(id="e1", school_id=_S1, auto_notify=True, completed_at=_T0)],
        students=[
            make_student(id="a", school_id=_S1, user_id="ua", name="Ann"),
            make_student(id="b", school_id=_S1, user_id="ub", name="Bob"),
        ],
        appearances=[
            make_appearance(student_id="a", media_id="m1", event_id="e1"),
            make_appearance(student_id="b", media_id="m1", event_id="e1"),
        ],
        reads=reads,
    )
    roster = await svc.event_roster(school_id=_S1, event_id="e1")
    assert roster.announced is True
    by_id = {e.student.id: e for e in roster.entries}
    assert by_id["a"].seen is True
    assert by_id["b"].seen is False


# ---- composite best-effort ---------------------------------------------


async def test_composite_notifier_isolates_a_failing_channel() -> None:
    ok = FakeNotificationChannel()
    boom = FakeNotificationChannel(raise_on_notify=RuntimeError("down"))
    composite = CompositeNotifier([boom, ok])
    events = FakeEventRepo([make_event(id="e1", school_id=_S1, completed_at=_T0)])
    svc = NotificationService(
        events,
        FakeMlResultsReader(
            [make_appearance(student_id="a", media_id="m1", event_id="e1")]
        ),
        FakeStudentRepo([make_student(id="a", school_id=_S1, user_id="ua")]),
        FakeNotificationReadRepo(),
        composite,
    )
    # The failing channel must not abort the notify nor the healthy channel.
    count = await svc.notify_event(school_id=_S1, event_id="e1")
    assert count == 1
    assert len(ok.sent) == 1


async def test_composite_notifier_empty_is_noop() -> None:
    from backend.domain.models import NotificationEvent

    evt = NotificationEvent(
        school_id=_S1, student_id="a", student_name="Ann", contact="a@x.io",
        event_id="e1", event_name="E", event_date=None, media_count=1,
    )
    await CompositeNotifier([]).notify(evt)  # BE_NOTIFICATION_CHANNELS="" — no-op, no error
