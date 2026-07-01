"""OpenCV video frame extractor — the cross-platform ``VideoFrameExtractor``
fallback (architecture §6).

Samples frames at a fixed target FPS and yields each as an encoded ``Frame`` (so
the detector's ``detect(image_bytes)`` contract holds). Used where decord has no
wheel (e.g. Windows dev) and as the documented fallback. OpenCV's ``VideoCapture``
needs a path, so the bytes are written to a temp file for the read.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

from ml_service.adapters._imaging import encode_image_bgr
from ml_service.domain.errors import MediaDecodeError
from ml_service.domain.models import Frame


class OpenCvFrameExtractor:
    """Fixed-FPS frame sampling via OpenCV."""

    def __init__(self, encode_ext: str = ".jpg") -> None:
        self._ext = encode_ext

    def extract(self, video_bytes: bytes, fps: float) -> Iterator[Frame]:
        import cv2

        fd, tmp = tempfile.mkstemp(suffix=".video")
        with os.fdopen(fd, "wb") as f:
            f.write(video_bytes)
        cap = cv2.VideoCapture(tmp)
        try:
            if not cap.isOpened():
                raise MediaDecodeError("OpenCV could not open the video")
            native = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
            step = max(1, round(native / fps)) if native > 0 and fps > 0 else 1
            i = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if i % step == 0:
                    ts = int(round(i / native * 1000)) if native > 0 else None
                    yield Frame(encode_image_bgr(frame, self._ext), ts)
                i += 1
        finally:
            cap.release()
            if os.path.exists(tmp):
                os.remove(tmp)
