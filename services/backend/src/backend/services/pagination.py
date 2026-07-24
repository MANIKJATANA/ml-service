"""A generic page container for the server-paginated list use-cases (BP9, decisions/0055).

One immutable value: the page's ``items`` + the unpaginated ``total`` + the echoed
``limit``/``offset``. The API ``*PageResponse.from_page`` envelopes read exactly these four
fields; the concrete item type varies per list (a listing DTO, a ``User``, a ``Media``).
Pure stdlib — safe to import from the pure services (layering).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    total: int
    limit: int
    offset: int
