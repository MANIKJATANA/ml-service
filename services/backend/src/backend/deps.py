"""FastAPI dependency wiring → the composition root (:mod:`wiring.container`).

The container is a process-wide singleton (built from ``settings`` once). Feature
routers land in later phases; they will depend on ``get_container`` and per-request
helpers added here (DB session, current user, permission checks).
"""

from __future__ import annotations

from functools import lru_cache

from backend.settings import settings
from backend.wiring.container import Container


@lru_cache(maxsize=1)
def get_container() -> Container:
    """The process-wide container (memoized)."""
    return Container(settings)
