"""Unit tests for the ML enrollment HTTP response parser (decisions/0026).

`_to_outcome` maps the ML enrollment API body to an `EnrollmentOutcome`. It has real
branching (missing fields, non-dict entries, malformed types) and is not exercised by
the fake-backed service/route tests — pin its behavior directly here. No network.
"""

from __future__ import annotations

import pytest
from backend.adapters.ml_client.http_enrollment import _to_outcome
from backend.domain.errors import UpstreamError


def test_parses_well_formed_body() -> None:
    outcome = _to_outcome(
        {
            "school_id": "s1",
            "student_id": "stu1",
            "embeddings_stored": 2,
            "photo_results": [
                {"index": 0, "status": "enrolled", "detail": None},
                {"index": 1, "status": "no_face", "detail": "no face found"},
            ],
        }
    )
    assert outcome.embeddings_stored == 2
    assert [p.status for p in outcome.photo_results] == ["enrolled", "no_face"]
    assert outcome.photo_results[1].detail == "no face found"


def test_missing_photo_results_defaults_empty() -> None:
    outcome = _to_outcome({"embeddings_stored": 0})
    assert outcome.embeddings_stored == 0
    assert outcome.photo_results == ()


def test_non_dict_entries_are_filtered() -> None:
    outcome = _to_outcome(
        {"embeddings_stored": 1, "photo_results": ["oops", {"index": 0, "status": "x"}]}
    )
    assert len(outcome.photo_results) == 1
    assert outcome.photo_results[0].status == "x"


def test_non_object_body_raises_upstream() -> None:
    with pytest.raises(UpstreamError):
        _to_outcome(["not", "a", "dict"])


def test_malformed_field_type_raises_upstream() -> None:
    # A bad embeddings_stored type must be a loud UpstreamError, not a bare ValueError.
    with pytest.raises(UpstreamError):
        _to_outcome({"embeddings_stored": "abc"})
