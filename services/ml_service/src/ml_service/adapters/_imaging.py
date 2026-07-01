"""Shared image decoding for adapters.

Decoding bytes → a BGR ``numpy`` array is common to the detector, embedder, and
video extractors. Sharing this helper is fine for NFR-1: it touches no *model*,
only OpenCV's codec. The model-swappability rule is about keeping the detector
and embedder *models* in separate modules, which they are.
"""

from __future__ import annotations

import cv2
import numpy as np

from ml_service.domain.errors import MediaDecodeError


def decode_image_bgr(image_bytes: bytes) -> np.ndarray:
    """Decode encoded image bytes (JPEG/PNG/...) into a BGR ``HxWx3`` array.

    Raises ``MediaDecodeError`` (permanent, non-retryable) on undecodable bytes.
    """
    if not image_bytes:
        raise MediaDecodeError("empty image bytes")
    buf = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise MediaDecodeError("could not decode image bytes (corrupt/unsupported)")
    return img


def encode_image_bgr(image_bgr: np.ndarray, ext: str = ".jpg") -> bytes:
    """Encode a BGR array back to bytes (used by the video extractors so a
    ``Frame`` carries encoded bytes, matching the ``Frame.image_bytes`` contract)."""
    ok, buf = cv2.imencode(ext, image_bgr)
    if not ok:
        raise MediaDecodeError(f"could not encode frame to {ext}")
    return buf.tobytes()
