"""OpenCV frame extractor — synthesizes a tiny AVI, then samples it.

Skips gracefully if no MJPG writer is available on the platform.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pytest
from ml_service.adapters.video.opencv_extractor import OpenCvFrameExtractor


def _make_avi(path: pathlib.Path, frames: int = 10, fps: int = 10) -> bool:
    import cv2

    fourcc = cv2.VideoWriter_fourcc(*"MJPG")  # type: ignore[attr-defined]
    writer = cv2.VideoWriter(str(path), fourcc, fps, (64, 64))
    if not writer.isOpened():
        return False
    for i in range(frames):
        img = np.full((64, 64, 3), (i * 20) % 255, dtype=np.uint8)
        writer.write(img)
    writer.release()
    return True


def test_extract_samples_frames(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "clip.avi"
    if not _make_avi(path):
        pytest.skip("no MJPG VideoWriter on this platform")
    data = path.read_bytes()
    extractor = OpenCvFrameExtractor()
    result = list(extractor.extract(data, fps=5.0))  # 10fps native, step 2
    assert result, "expected at least one sampled frame"
    assert all(isinstance(f.image_bytes, (bytes, bytearray)) for f in result)
    assert all(len(f.image_bytes) > 0 for f in result)
    assert result[0].timestamp_ms is not None
