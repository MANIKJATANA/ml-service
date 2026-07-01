"""SCRFD face detector (InsightFace ``buffalo_l`` bundle) — the default
``FaceDetector`` adapter (architecture §6).

Loads **only** the detection model (``det_10g.onnx``) from the bundle so it stays
independent of the embedder (NFR-1). Returns ``FaceBox`` with the 5-point
landmarks SCRFD produces, which the ArcFace embedder needs for alignment
(decisions/0013). The synchronous ONNX call is offloaded to a worker thread so
the async port stays non-blocking.
"""

from __future__ import annotations

import os
from typing import Any

import anyio
import numpy as np

from ml_service.adapters._imaging import decode_image_bgr
from ml_service.domain.errors import ConfigurationError
from ml_service.domain.models import FaceBox

DEFAULT_MODEL_FILE = "det_10g.onnx"


class SCRFDDetector:
    """Detects faces with InsightFace SCRFD. ``version`` identifies the model for
    reproducibility (NFR-4)."""

    version: str

    def __init__(
        self,
        model_dir: str,
        *,
        model_file: str = DEFAULT_MODEL_FILE,
        det_size: tuple[int, int] = (640, 640),
        det_thresh: float = 0.5,
        providers: list[str] | None = None,
        ctx_id: int = -1,
        version: str | None = None,
    ) -> None:
        # Imported lazily: insightface ships only on the Linux image (see
        # pyproject markers); importing at module load would break Windows dev.
        from insightface.model_zoo import get_model

        path = os.path.join(model_dir, model_file)
        if not os.path.exists(path):
            raise ConfigurationError(f"SCRFD model not found: {path}")
        self._model: Any = get_model(
            path, providers=providers or ["CPUExecutionProvider"]
        )
        self._model.prepare(ctx_id=ctx_id, input_size=det_size, det_thresh=det_thresh)
        self.version = version or f"scrfd:{model_file}"

    async def detect(self, image_bytes: bytes) -> list[FaceBox]:
        return await anyio.to_thread.run_sync(self._detect_sync, image_bytes)

    def _detect_sync(self, image_bytes: bytes) -> list[FaceBox]:
        img = decode_image_bgr(image_bytes)
        bboxes, kpss = self._model.detect(img, max_num=0, metric="default")
        boxes: list[FaceBox] = []
        for i in range(len(bboxes)):
            x1, y1, x2, y2, score = (float(v) for v in bboxes[i][:5])
            landmarks: tuple[tuple[float, float], ...] | None = None
            if kpss is not None and len(kpss) > i:
                landmarks = tuple(
                    (float(pt[0]), float(pt[1])) for pt in np.asarray(kpss[i])
                )
            boxes.append(FaceBox(x1, y1, x2, y2, score, landmarks))
        return boxes
