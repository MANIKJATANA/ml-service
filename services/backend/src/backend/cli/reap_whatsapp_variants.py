"""Reap stale WhatsApp send-variant objects (W3a).

    python -m backend.cli.reap_whatsapp_variants [--older-than-hours N] [--dry-run] [--school ID]

W2 uploads a ≤5 MB "send variant" of each photo to
``{BE_WHATSAPP_VARIANT_PREFIX}/{school_id}/{media_id}.jpg`` and mints a short-lived signed
URL (TTL ``BE_DOWNLOAD_URL_TTL_S``, default 1h). Those objects are never deleted otherwise
— one small private JPEG accumulates per distinct media ever sent — so run this on a cron /
one-shot to clean them up. It only deletes objects OLDER than the retention window (default
``BE_WHATSAPP_VARIANT_RETENTION_HOURS`` = 24h, well past the 1h URL TTL), so it can't race a
fresh send; a reaped variant is re-created on the next send (the key is deterministic).

Best-effort: one object's delete failure is counted and the run continues.

Requires ``BE_DATABASE_URL`` only insofar as the container builds; the reaper itself uses
just the object store (set ``BE_OBJECT_STORE_IMPL=supabase`` + its creds for a real reap).
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta

from backend.services.whatsapp_variant_reaper import (
    ReapSummary,
    reap_whatsapp_variants,
)
from backend.settings import settings
from backend.wiring.container import Container


def _positive_hours(raw: str) -> float:
    """argparse validator: a retention of <= 0h would set the cutoff to now (or the future),
    reaping fresh in-flight variants — reject it at the boundary, before the container builds."""
    value = float(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError(
            "must be > 0 (a value <= 0 would reap fresh, in-flight variants)"
        )
    return value


async def _run(older_than_hours: float, *, dry_run: bool, school_id: str | None) -> int:
    container = Container(settings)
    try:
        summary: ReapSummary = await reap_whatsapp_variants(
            container.object_store(),
            prefix=settings.whatsapp_variant_prefix,
            retention=timedelta(hours=older_than_hours),
            dry_run=dry_run,
            school_id=school_id,
        )
        verb = "would delete" if dry_run else "deleted"
        print(
            f"reaped WhatsApp variants (prefix={settings.whatsapp_variant_prefix!r}, "
            f"older_than={older_than_hours}h"
            + (f", school={school_id}" if school_id else "")
            + (", dry-run" if dry_run else "")
            + "):"
        )
        print(
            f"  scanned={summary.scanned}  {verb}={summary.deleted}  "
            f"skipped_recent={summary.skipped_recent}  errors={summary.errors}"
        )
        return 0
    finally:
        await container.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="backend.cli.reap_whatsapp_variants",
        description="Delete stale WhatsApp send-variant objects (W3a).",
    )
    parser.add_argument(
        "--older-than-hours",
        type=_positive_hours,
        default=float(settings.whatsapp_variant_retention_hours),
        help=(
            "delete variants older than this many hours, must be > 0 "
            f"(default {settings.whatsapp_variant_retention_hours})"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be deleted without deleting anything",
    )
    parser.add_argument(
        "--school",
        default=None,
        help="only reap this school's variants (default: all schools under the prefix)",
    )
    args = parser.parse_args(argv)

    return asyncio.run(
        _run(args.older_than_hours, dry_run=args.dry_run, school_id=args.school)
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
