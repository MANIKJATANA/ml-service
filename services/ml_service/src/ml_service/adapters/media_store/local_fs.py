"""Local-filesystem ``MediaStore`` — dev/test + offline CI (architecture §5).

A real, architecture-sanctioned adapter (not a mock): reads media bytes from a
mounted directory. ``media_uri`` may be a ``file://`` URL, an absolute path, or a
path relative to ``base_dir``.
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlparse

import anyio

from ml_service.domain.errors import MediaFetchError


class LocalFsMediaStore:
    """Fetches media bytes from the local filesystem."""

    def __init__(self, base_dir: str) -> None:
        self._base = base_dir

    async def fetch(self, media_uri: str) -> bytes:
        return await anyio.to_thread.run_sync(self._fetch_sync, media_uri)

    def _fetch_sync(self, media_uri: str) -> bytes:
        path = self._resolve(media_uri)
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError as exc:
            raise MediaFetchError(f"could not read media {media_uri!r}: {exc}") from exc

    def _resolve(self, media_uri: str) -> str:
        uri = media_uri
        if uri.startswith("file://"):
            parsed = urlparse(uri)
            uri = unquote(parsed.path)
            # urlparse leaves a leading slash before a Windows drive (/C:/...).
            if os.name == "nt" and len(uri) >= 3 and uri[0] == "/" and uri[2] == ":":
                uri = uri[1:]
        if os.path.isabs(uri):
            return uri
        return os.path.join(self._base, uri)
