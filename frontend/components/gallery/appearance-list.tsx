"use client";

import { Spinner } from "@/components/ui/spinner";
import { StatusPill } from "@/components/ui/status-pill";
import type { MediaAppearanceResponse } from "@/lib/api/types";

/** Who appears in a photo — name + a "Review" flag for low-confidence matches +
 *  the confidence percent. Shared by the Lightbox and the photo detail page (0035). */
export function AppearanceList({
  appearances,
  isLoading,
}: {
  appearances: MediaAppearanceResponse[] | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="flex justify-center py-4">
        <Spinner className="size-5 text-ink-muted" />
      </div>
    );
  }
  if (!appearances || appearances.length === 0) {
    return <p className="text-body-sm text-ink-secondary">No students matched in this photo.</p>;
  }
  return (
    <ul className="flex flex-col gap-2.5">
      {appearances.map((appearance) => (
        <li key={appearance.student_id} className="flex items-center justify-between gap-2">
          <span className="min-w-0 flex-1 truncate text-body-sm text-ink">{appearance.name}</span>
          <div className="flex shrink-0 items-center gap-2">
            {appearance.needs_review ? <StatusPill tone="warning">Review</StatusPill> : null}
            <span className="text-tabular tabular-nums text-ink-secondary">
              {Math.round(appearance.confidence * 100)}%
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}
