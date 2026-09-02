"""Platform-wide config use-cases (W-live-test).

Pure orchestration over the platform-config repo — no HTTP, no RBAC (authorization is at the
route: platform-admin only), no crypto. Two features:

- The Meta access token: a UI-editable secret stored in the DB (owner decision). This service
  reads/writes it, but the API layer NEVER returns it in full (the response exposes only
  ``token_set``/``token_last4``) and it is never logged. The container reads it (with an env
  fallback) to build the sender's per-send token provider.
- The interim free-form send: ``interim_test_number`` + ``interim_mode`` drive an interim path
  (a text intro + N real photos to a hardcoded test number).

Reads return the row or a synthesized "empty" default (all None/false) so the route always has
something to render; ``set_config`` is a PARTIAL update — a ``None`` field is left unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.domain.models import PlatformConfig
from backend.domain.ports import PlatformConfigRepository

_SINGLETON_ID = "platform"


def _clean(value: str | None) -> str | None:
    """Trim an optional string; blank → None (so a whitespace-only edit clears the field). A
    genuinely-omitted field is passed as ``None`` by the caller and stays unchanged in the repo."""
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class PlatformConfigService:
    def __init__(self, repo: PlatformConfigRepository) -> None:
        self._repo = repo

    async def get_config(self) -> PlatformConfig:
        """The platform config, or a synthesized "not configured" default (no token, no interim
        number, interim off) when never saved."""
        config = await self._repo.get()
        if config is not None:
            return config
        now = datetime.now(UTC)
        return PlatformConfig(
            id=_SINGLETON_ID,
            meta_access_token=None,
            interim_test_number=None,
            interim_mode=False,
            created_at=now,
            updated_at=now,
        )

    async def set_config(
        self,
        *,
        meta_access_token: str | None = None,
        interim_test_number: str | None = None,
        interim_mode: bool | None = None,
    ) -> PlatformConfig:
        """Create/replace the platform config — a PARTIAL update, so ``None`` leaves a field
        unchanged (a caller can save just the token, or just the number/mode). String fields are
        trimmed (blank → None)."""
        return await self._repo.upsert(
            meta_access_token=_clean(meta_access_token),
            interim_test_number=_clean(interim_test_number),
            interim_mode=interim_mode,
        )
