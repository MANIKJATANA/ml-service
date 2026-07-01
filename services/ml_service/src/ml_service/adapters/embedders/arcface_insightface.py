"""ArcFace face embedder (InsightFace ``buffalo_l`` bundle) — the default
``FaceEmbedder`` adapter (architecture §6).

Loads **only** the recognition model (``w600k_r50.onnx``) so it stays independent
of the detector (NFR-1). Aligns the crop with the detector's 5-point landmarks
(ArcFace's ``norm_crop``) when present, else falls back to a plain bbox
crop-and-resize. Always returns a 512-d **L2-normalized** vector so cosine
similarity == inner product (locked convention, ``domain/models.py``). The sync
ONNX call is offloaded to a worker thread.
"""

from __future__ import annotations

import os
from typing import Any

import anyio
import numpy as np

from ml_service.adapters._imaging import decode_image_bgr
from ml_service.domain.errors import ConfigurationError, MLServiceError
from ml_service.domain.models import EMBEDDING_DIM, Embedding, FaceBox

DEFAULT_MODEL_FILE = "w600k_r50.onnx"


class ArcFaceEmbedder:
    """Produces L2-normalized ArcFace embeddings. ``version`` identifies the model
    for reproducibility (NFR-4)."""

    version: str

    def __init__(
        self,
        model_dir: str,
        *,
        model_file: str = DEFAULT_MODEL_FILE,
        image_size: int = 112,
        providers: list[str] | None = None,
        ctx_id: int = -1,
        version: str | None = None,
    ) -> None:
        from insightface.model_zoo import get_model

        path = os.path.join(model_dir, model_file)
        if not os.path.exists(path):
            raise ConfigurationError(f"ArcFace model not found: {path}")
        self._model: Any = get_model(
            path, providers=providers or ["CPUExecutionProvider"]
        )
        self._model.prepare(ctx_id=ctx_id)
        self._image_size = image_size
        self.version = version or f"arcface:{model_file}"

    async def embed(self, image_bytes: bytes, face_box: FaceBox) -> Embedding:
        return await anyio.to_thread.run_sync(self._embed_sync, image_bytes, face_box)

    def _embed_sync(self, image_bytes: bytes, face_box: FaceBox) -> Embedding:
        from insightface.utils import face_align

        img = decode_image_bgr(image_bytes)
        if face_box.landmarks is not None:
            landmark = np.asarray(face_box.landmarks, dtype=np.float32)
            aimg = face_align.norm_crop(
                img, landmark=landmark, image_size=self._image_size
            )
        else:
            aimg = self._crop_resize(img, face_box)

        feat = np.asarray(self._model.get_feat(aimg), dtype=np.float32).reshape(-1)
        if feat.shape[0] != EMBEDDING_DIM:
            raise MLServiceError(
                f"embedder produced {feat.shape[0]} dims, expected {EMBEDDING_DIM}"
            )
        norm = float(np.linalg.norm(feat))
        if norm == 0.0:
            raise MLServiceError("degenerate (zero-norm) embedding")
        feat = feat / norm
        return Embedding(tuple(float(v) for v in feat))

    def _crop_resize(self, img: np.ndarray, face_box: FaceBox) -> np.ndarray:
        """Landmark-free fallback: clamp the bbox to the image and resize to the
        model's input size. Lower quality than aligned crops — only used when the
        detector supplied no landmarks."""
        import cv2

        h, w = img.shape[:2]
        x1 = max(0, int(face_box.x1))
        y1 = max(0, int(face_box.y1))
        x2 = min(w, int(face_box.x2))
        y2 = min(h, int(face_box.y2))
        if x2 <= x1 or y2 <= y1:
            raise MLServiceError("degenerate face box for crop-resize fallback")
        crop = img[y1:y2, x1:x2]
        return cv2.resize(crop, (self._image_size, self._image_size))
