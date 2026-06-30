"""The pure match-decision function (requirements §6.2). No side effects."""

from __future__ import annotations

from ml_service.domain.models import Candidate, Emission, Thresholds


def apply_threshold_and_gap(
    candidates: list[Candidate], thresholds: Thresholds
) -> list[Emission]:
    """Decide which candidates to emit for a single detected face (req §6.2).

    Defensive about its input: it first filters by ``score >= match_confidence``,
    then **collapses to the best candidate per ``student_id``** (search can return
    the same student more than once under multi-vector enrollment — see the
    ``VectorIndex.search`` contract), then **sorts by score descending**. The
    top-1/top-2 it compares are therefore always distinct students. For input that
    is already distinct-per-student and sorted, the result is identical.

    Behaviour after collapse + sort:

    - 0 above threshold -> ``[]`` (unknown face: caller logs, emits no record).
    - 1 above threshold -> emit it with ``needs_review=False``.
    - 2+ above threshold -> if ``top1 - top2 > gap`` emit ``top1`` alone
      (``needs_review=False``); otherwise emit both ``top1`` and ``top2`` with
      ``needs_review=True``.

    Only the top two (deduped) candidates are considered, regardless of ``top_k``.
    """
    filtered = [c for c in candidates if thresholds.clears(c.score)]
    if not filtered:
        return []
    # Collapse to each student's best hit (multi-vector enrollment can surface the
    # same student twice), preserving first-seen order, then sort by score desc.
    best_per_student: dict[str, Candidate] = {}
    for c in filtered:
        existing = best_per_student.get(c.student_id)
        if existing is None or c.score > existing.score:
            best_per_student[c.student_id] = c
    ranked = sorted(best_per_student.values(), key=lambda c: c.score, reverse=True)
    if len(ranked) == 1:
        return [Emission(ranked[0], needs_review=False)]
    top1, top2 = ranked[0], ranked[1]
    if top1.score - top2.score > thresholds.gap:
        return [Emission(top1, needs_review=False)]
    return [Emission(top1, needs_review=True), Emission(top2, needs_review=True)]
