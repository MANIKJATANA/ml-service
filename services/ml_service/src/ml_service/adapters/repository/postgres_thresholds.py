"""Postgres ``ThresholdProvider`` — per-school thresholds with global-default
fallback (req §6.1) and a short read-through cache (architecture §6).

Reads ``school_thresholds``; a missing row or a null column falls back to the
configured global default. Results are cached per school for ``cache_ttl_s`` (60s
default) so inference doesn't hit the DB every job — schools rarely change
thresholds.
"""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ml_service.db.models import SchoolThreshold
from ml_service.domain.models import Thresholds


class PostgresThresholdProvider:
    """Resolves per-school thresholds, cached with a TTL."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        default_match_confidence: float,
        default_gap: float,
        cache_ttl_s: float = 60.0,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._default_match_confidence = default_match_confidence
        self._default_gap = default_gap
        self._ttl = cache_ttl_s
        self._cache: dict[str, tuple[Thresholds, float]] = {}

    async def get_thresholds(self, school_id: str) -> Thresholds:
        now = time.monotonic()
        cached = self._cache.get(school_id)
        if cached is not None and cached[1] > now:
            return cached[0]
        thresholds = await self._load(school_id)
        self._cache[school_id] = (thresholds, now + self._ttl)
        return thresholds

    async def _load(self, school_id: str) -> Thresholds:
        stmt = select(
            SchoolThreshold.match_confidence_threshold,
            SchoolThreshold.gap_threshold,
        ).where(SchoolThreshold.school_id == school_id)
        async with self._sessionmaker() as session:
            row = (await session.execute(stmt)).first()

        match_confidence = self._default_match_confidence
        gap = self._default_gap
        if row is not None:
            if row[0] is not None:
                match_confidence = row[0]
            if row[1] is not None:
                gap = row[1]
        return Thresholds(match_confidence=match_confidence, gap=gap)
