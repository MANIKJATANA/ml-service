"""Domain value-object invariants (domain/models.py)."""

import pytest
from ml_service.domain.models import Embedding, FaceBox


def test_embedding_wrong_length_raises() -> None:
    with pytest.raises(ValueError):
        Embedding((0.0,))


def test_embedding_correct_length_constructs() -> None:
    emb = Embedding(tuple([0.0] * 512))
    assert len(emb.vector) == 512


def test_facebox_area() -> None:
    assert FaceBox(0, 0, 100, 100, 0.9).area == 10000.0


def test_facebox_area_zero_for_degenerate_box() -> None:
    assert FaceBox(0, 0, 0, 0, 0.9).area == 0.0
    assert FaceBox(100, 100, 0, 0, 0.9).area == 0.0
