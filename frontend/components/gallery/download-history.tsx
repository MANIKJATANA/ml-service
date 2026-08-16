"use client";

import { ChevronDown, ChevronUp, History } from "lucide-react";
import { useState } from "react";

import { ROLE_LABELS } from "@/lib/auth/routes";
import { useMe } from "@/lib/hooks/use-me";
import { useMediaDownloadLog } from "@/lib/hooks/use-audit";
import { formatDateTime } from "@/lib/utils";

/** School-admin-only download history for one photo (BP8b, decisions/0050). Renders nothing
 *  for anyone else (the `audit:view` endpoint is admin-only), so it can be dropped into any
 *  staff media surface unconditionally. Collapsed by default; the count shows on the toggle. */
export function DownloadHistory({ mediaId }: { mediaId: string }) {
  const { user } = useMe();
  const isAdmin = user?.role === "school_admin";
  const { log, error, isLoading } = useMediaDownloadLog(mediaId, Boolean(isAdmin));
  const [open, setOpen] = useState(false);

  if (!isAdmin) {
    // BP21 (R3-S5-11): teachers can download but were never told it's recorded + admin-visible
    // — surveillance discovered, not disclosed. Show a one-line disclosure (no fetch; the log
    // itself stays admin-only). Non-staff surfaces don't render this component.
    return user?.role === "teacher" ? (
      <p className="text-body-sm text-ink-muted">
        <History className="mr-1 inline size-3.5 align-[-2px]" aria-hidden="true" />
        Downloads are recorded and visible to your school&apos;s admins.
      </p>
    ) : null;
  }

  const count = log?.count ?? 0;

  if (error) {
    return (
      <p className="text-body-sm text-ink-muted" role="alert">
        Couldn&apos;t load download history.
      </p>
    );
  }

  if (isLoading && !log) {
    return <p className="text-body-sm text-ink-muted">Loading download history…</p>;
  }

  if (count === 0) {
    return (
      <p className="text-body-sm text-ink-muted">
        <History className="mr-1 inline size-3.5 align-[-2px]" aria-hidden="true" />
        Not downloaded yet
      </p>
    );
  }

  const label = `Downloaded ${count} ${count === 1 ? "time" : "times"}`;

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-body-sm font-medium text-ink-secondary transition-colors hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-button"
      >
        <History className="size-3.5" aria-hidden="true" />
        {label}
        {open ? (
          <ChevronUp className="size-3.5" aria-hidden="true" />
        ) : (
          <ChevronDown className="size-3.5" aria-hidden="true" />
        )}
      </button>
      {open ? (
        <ul className="flex flex-col gap-2">
          {log?.entries.map((e) => (
            <li key={e.id} className="flex flex-col gap-0.5 text-body-sm">
              <span className="text-ink">
                {e.actor_email ?? "Removed account"}
                <span className="ml-1.5 text-ink-muted">
                  {ROLE_LABELS[e.actor_role]}
                </span>
              </span>
              <span className="text-ink-muted">
                <time dateTime={e.downloaded_at}>{formatDateTime(e.downloaded_at)}</time>
                {e.subject_student_name ? ` · as ${e.subject_student_name}` : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
