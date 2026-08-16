"use client";

import Link from "next/link";

import { StudentRefAvatar } from "@/components/gallery/student-ref-avatar";
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
  const hasConfidence = appearances.some((a) => a.confidence !== null);
  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col gap-2.5">
        {appearances.map((appearance) => (
          <li key={appearance.student_id} className="flex items-center gap-2">
            {/* BP22: the student's reference face next to their name (staff surface only). */}
            <StudentRefAvatar studentId={appearance.student_id} name={appearance.name} className="size-8" />
            <span className="min-w-0 flex-1 truncate text-body-sm text-ink">{appearance.name}</span>
            <div className="flex shrink-0 items-center gap-2">
              {appearance.verdict === "added" ? (
                <StatusPill tone="info">Added</StatusPill>
              ) : appearance.verdict === "confirmed" ? (
                <StatusPill tone="success">Confirmed</StatusPill>
              ) : appearance.verdict === "rejected" ? (
                <StatusPill tone="error">Rejected</StatusPill>
              ) : appearance.needs_review ? (
                <StatusPill tone="warning">Review</StatusPill>
              ) : null}
              {appearance.confidence !== null ? (
                <span className="text-tabular tabular-nums text-ink-secondary">
                  {Math.round(appearance.confidence * 100)}%
                </span>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
      {/* BP21 (R3-S5-03): explain the confidence % and link the plain-language explainer. */}
      <p className="text-body-sm text-ink-secondary">
        {hasConfidence
          ? "Percentages are how sure the match is — a low one is worth a second look. "
          : null}
        <Link
          href="/how-matching-works"
          className="rounded underline hover:text-ink-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          How photo matching works
        </Link>
      </p>
    </div>
  );
}
