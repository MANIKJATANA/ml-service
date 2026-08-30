"""WhatsApp send-variant cleanup (W3a) — a pure reaper over the object store.

W2 uploads a ≤5 MB "send variant" of each photo to a deterministic key
``{whatsapp_variant_prefix}/{school_id}/{media_id}.jpg`` and mints a short-lived signed
URL for it (TTL ``download_url_ttl_s``, default 1h). A documented W2 limit is that those
variant OBJECTS are never deleted — one small private JPEG accumulates per distinct media
ever sent. This reaper deletes the stale ones.

Safety by construction: **age-based only** — it never deletes an object younger than
``retention`` (default 24h, well past the 1h signed-URL TTL), so it can't race a fresh
send; and a variant is safely re-creatable (the key is deterministic + overwritten on the
next send). Best-effort: one object's delete failure is counted and the run continues (the
BP27/W2 pattern). Pure orchestration over the ``ObjectStore`` port only — no IO library,
no ``datetime`` clock read except the injectable ``now`` — so ``tests/test_layering.py``
stays green.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog

from backend.domain.errors import UpstreamError
from backend.domain.ports import ObjectStore

_log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReapSummary:
    """The outcome of one reaper run. ``scanned`` = objects listed under the prefix;
    ``deleted`` = old objects removed (0 in a dry run); ``skipped_recent`` = objects kept
    because they're younger than ``retention``; ``errors`` = per-object delete failures (the
    run continued past each)."""

    scanned: int
    deleted: int
    skipped_recent: int
    errors: int


async def reap_whatsapp_variants(
    object_store: ObjectStore,
    *,
    prefix: str,
    retention: timedelta,
    now: datetime | None = None,
    dry_run: bool = False,
    school_id: str | None = None,
) -> ReapSummary:
    """Delete WhatsApp send-variant objects older than ``retention``.

    Lists every object under ``prefix`` (or ``{prefix}/{school_id}`` when ``school_id`` is
    given), keeps only those whose ``last_modified`` is at/before ``now - retention``, and
    (unless ``dry_run``) deletes each best-effort. ``now`` defaults to ``datetime.now(UTC)``
    (injectable for deterministic tests).
    """
    # Defense-in-depth (the CLI also guards this): a non-positive retention would set the
    # cutoff to now/the future and reap fresh, in-flight variants — refuse it.
    if retention <= timedelta(0):
        raise ValueError("retention must be positive (a <= 0 window would reap fresh variants)")
    if now is None:
        now = datetime.now(UTC)
    cutoff = now - retention

    scan_prefix = prefix.strip("/")
    if school_id:
        scan_prefix = f"{scan_prefix}/{school_id}"

    objects = await object_store.list_prefix(scan_prefix)

    scanned = len(objects)
    deleted = 0
    skipped_recent = 0
    errors = 0

    for obj in objects:
        if obj.last_modified > cutoff:
            skipped_recent += 1
            continue
        if dry_run:
            deleted += 1  # what WOULD be deleted
            continue
        try:
            await object_store.delete(obj.key)
        except UpstreamError:
            errors += 1
            _log.warning("whatsapp_variant_reap_delete_failed", object_key=obj.key)
            continue
        deleted += 1

    _log.info(
        "whatsapp_variant_reap_done",
        prefix=scan_prefix,
        retention_hours=retention.total_seconds() / 3600,
        dry_run=dry_run,
        scanned=scanned,
        deleted=deleted,
        skipped_recent=skipped_recent,
        errors=errors,
    )
    return ReapSummary(
        scanned=scanned,
        deleted=deleted,
        skipped_recent=skipped_recent,
        errors=errors,
    )
