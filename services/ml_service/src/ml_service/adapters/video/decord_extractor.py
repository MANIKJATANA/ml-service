"""decord video frame extractor — the default ``VideoFrameExtractor``
(architecture §6). 5–10× faster sampling than OpenCV.

Yields each sampled frame as an encoded ``Frame`` (BGR → JPEG) so the detector's
``detect(image_bytes)`` contract holds. decord ships only on the Linux image (see
pyproject markers); the OpenCV extractor is the cross-platform fallback.
"""

from __future__ import annotations

import io
from collections.abc import Iterator

from ml_service.adapters._imaging import encode_image_bgr
from ml_service.domain.models import Frame


class DecordFrameExtractor:
    """Fixed-FPS frame sampling via decord."""

    def __init__(self, encode_ext: str = ".jpg") -> None:
        self._ext = encode_ext

    def extract(self, video_bytes: bytes, fps: float) -> Iterator[Frame]:
        import cv2
        from decord import VideoReader, cpu

        reader = VideoReader(io.BytesIO(video_bytes), ctx=cpu(0))
        native = float(reader.get_avg_fps()) or 0.0
        step = max(1, round(native / fps)) if native > 0 and fps > 0 else 1
        for i in range(0, len(reader), step):
            rgb = reader[i].asnumpy()
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            ts = int(round(i / native * 1000)) if native > 0 else None
            yield Frame(encode_image_bgr(bgr, self._ext), ts)
