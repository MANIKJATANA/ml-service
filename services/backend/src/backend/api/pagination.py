"""Shared list-pagination Query params (BP9, decisions/0055).

One ``limit``/``offset`` contract across every paginated list route, mirroring the BP8b audit
endpoint. The page-size default + max come from settings (``BE_DEFAULT_PAGE_SIZE`` /
``BE_MAX_PAGE_SIZE``); an out-of-range ``limit``/``offset`` 422s via the ``Query`` bounds.
Each route names its own ``sort`` enum (so an unknown sort 422s for free) and maps the shared
``SortDir`` to the services' ``descending`` bool.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Query

from backend.domain.models import SortDir
from backend.settings import settings

DEFAULT_PAGE_SIZE = settings.default_page_size
MAX_PAGE_SIZE = settings.max_page_size

LimitQuery = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
OffsetQuery = Annotated[int, Query(ge=0)]
SearchQuery = Annotated[str | None, Query(max_length=200)]


def is_descending(direction: SortDir) -> bool:
    """Map a ``SortDir`` query value to the services' ``descending`` flag."""
    return direction is SortDir.DESC
