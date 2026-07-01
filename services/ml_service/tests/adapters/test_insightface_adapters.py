"""InsightFace detector + embedder against the real buffalo_l models.

Requires the (Linux-only) ``insightface`` package plus:
  - ``ML_MODEL_DIR``  — dir holding det_10g.onnx + w600k_r50.onnx
  - ``ML_TEST_FACE_IMAGE`` — path to a JPEG/PNG with one clear face
Skipped otherwise, so CI/Windows dev stays green.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("insightface")

from ml_service.adapters.detectors.scrfd_insightface import SCRFDDetector  # noqa: E402
from ml_service.adapters.embedders.arcface_insightface import (  # noqa: E402
    ArcFaceEmbedder,
)
from ml_service.domain.models import EMBEDDING_DIM  # noqa: E402

MODEL_DIR = os.environ.get("ML_MODEL_DIR")
FACE_IMAGE = os.environ.get("ML_TEST_FACE_IMAGE")
pytestmark = pytest.mark.skipif(
    not (MODEL_DIR and FACE_IMAGE),
    reason="ML_MODEL_DIR / ML_TEST_FACE_IMAGE not set",
)


async def test_detect_then_embed_produces_normalized_512d() -> None:
    with open(FACE_IMAGE, "rb") as f:  # type: ignore[arg-type]
        image_bytes = f.read()
    detector = SCRFDDetector(MODEL_DIR)  # type: ignore[arg-type]
    boxes = await detector.detect(image_bytes)
    assert boxes, "expected at least one detected face"
    assert boxes[0].landmarks is not None and len(boxes[0].landmarks) == 5

    embedder = ArcFaceEmbedder(MODEL_DIR)  # type: ignore[arg-type]
    emb = await embedder.embed(image_bytes, boxes[0])
    assert len(emb.vector) == EMBEDDING_DIM
    norm = sum(v * v for v in emb.vector) ** 0.5
    assert abs(norm - 1.0) < 1e-3  # L2-normalized
