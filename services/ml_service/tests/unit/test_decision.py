"""Full threshold + gap decision matrix (requirements §6.2)."""

from ml_service.domain.decision import apply_threshold_and_gap
from ml_service.domain.models import Candidate, Thresholds

TH = Thresholds(match_confidence=0.5, gap=0.1)


def _c(student: str, score: float) -> Candidate:
    return Candidate(student, score)


def test_empty_candidates_returns_empty() -> None:
    assert apply_threshold_and_gap([], TH) == []


def test_all_below_threshold_returns_empty() -> None:
    assert apply_threshold_and_gap([_c("a", 0.4), _c("b", 0.3)], TH) == []


def test_single_above_threshold_emits_one() -> None:
    out = apply_threshold_and_gap([_c("a", 0.8)], TH)
    assert len(out) == 1
    assert out[0].candidate.student_id == "a"
    assert out[0].needs_review is False


def test_score_exactly_at_threshold_is_included() -> None:
    out = apply_threshold_and_gap([_c("a", 0.5)], TH)  # >= threshold
    assert len(out) == 1


def test_two_above_large_gap_emits_top1_only() -> None:
    out = apply_threshold_and_gap([_c("a", 0.9), _c("b", 0.6)], TH)  # gap 0.3 > 0.1
    assert len(out) == 1
    assert out[0].candidate.student_id == "a"
    assert out[0].needs_review is False


def test_gap_exactly_at_boundary_emits_both() -> None:
    # gap == threshold is NOT strictly greater -> ambiguous
    out = apply_threshold_and_gap([_c("a", 0.9), _c("b", 0.8)], TH)  # gap 0.1
    assert len(out) == 2
    assert all(e.needs_review for e in out)
    assert {e.candidate.student_id for e in out} == {"a", "b"}


def test_two_above_small_gap_emits_both_needs_review() -> None:
    out = apply_threshold_and_gap([_c("a", 0.9), _c("b", 0.85)], TH)  # gap 0.05 < 0.1
    assert len(out) == 2
    assert all(e.needs_review for e in out)


def test_one_above_one_below_is_single_confident() -> None:
    out = apply_threshold_and_gap([_c("a", 0.8), _c("b", 0.4)], TH)
    assert len(out) == 1
    assert out[0].candidate.student_id == "a"
    assert out[0].needs_review is False


def test_more_than_two_filtered_only_considers_top_two() -> None:
    out = apply_threshold_and_gap([_c("a", 0.9), _c("b", 0.85), _c("c", 0.7)], TH)
    assert len(out) == 2  # c is ignored
    assert {e.candidate.student_id for e in out} == {"a", "b"}


def test_pure_no_input_mutation() -> None:
    cands = [_c("a", 0.9), _c("b", 0.6)]
    snapshot = list(cands)
    apply_threshold_and_gap(cands, TH)
    assert cands == snapshot


def test_same_student_twice_collapses_to_one_emission() -> None:
    # Multi-vector enrollment can surface the same student twice; collapse to one.
    out = apply_threshold_and_gap([_c("x", 0.9), _c("x", 0.85)], TH)
    assert len(out) == 1
    assert out[0].candidate.student_id == "x"
    assert out[0].candidate.score == 0.9  # keeps the student's best hit
    assert out[0].needs_review is False


def test_unsorted_distinct_input_is_sorted_internally() -> None:
    out = apply_threshold_and_gap([_c("b", 0.6), _c("a", 0.9)], TH)
    assert out[0].candidate.student_id == "a"  # top1 is the higher score


def test_duplicate_student_then_distinct_lower_collapses_then_gaps() -> None:
    # After per-student collapse top1=x(0.9), top2=y(0.6); gap 0.3 > 0.1 -> single.
    out = apply_threshold_and_gap([_c("x", 0.9), _c("x", 0.88), _c("y", 0.6)], TH)
    assert len(out) == 1
    assert out[0].candidate.student_id == "x"
    assert out[0].needs_review is False
