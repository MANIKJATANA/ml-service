import type { EventProcessingStatus, EventStatus } from "@/lib/api/types";

type Tone = "neutral" | "success" | "warning" | "error" | "info";

/**
 * Event lifecycle (active/archived) → StatusPill tone + label. Both neutral: "active" is
 * the resting state, not a success — colour is reserved for the processing ramp below.
 */
export const EVENT_STATUS_TONE: Record<EventStatus, Tone> = {
  active: "neutral",
  archived: "neutral",
};
export const EVENT_STATUS_LABEL: Record<EventStatus, string> = {
  active: "Active",
  archived: "Archived",
};

/**
 * Event-level face-MATCHING state → tone + label (the FE polls this). Colour arrives only when
 * work is actually happening: not_started/queued stay neutral, matching = info (live),
 * matched = success. BP21: one grammar — "Match" (find who's in each photo), never
 * "Process"/"Distribution". (The separate ANNOUNCE step has its own pill in the DistributionCard.)
 */
export const PROCESSING_TONE: Record<EventProcessingStatus, Tone> = {
  not_started: "neutral",
  queued: "neutral",
  processing: "info",
  completed: "success",
  failed: "error", // BP19a: the job dead-lettered — a visible, retryable failure
};
export const PROCESSING_LABEL: Record<EventProcessingStatus, string> = {
  not_started: "Not started",
  queued: "Queued",
  processing: "Matching",
  completed: "Matched",
  failed: "Matching failed",
};

/**
 * BP19c: the FE mirror of BE_EVENT_INFLIGHT_STALE_S — an event in-flight longer than this is
 * treated as stuck (drives the "taking longer than usual" cue + the stale-in-flight Retry the
 * backend's widened guard allows). Keep it >= the backend value so the FE never offers a retry
 * the backend would still 400. Defaults to 30 min, matching the backend default.
 */
export const EVENT_INFLIGHT_STALE_MS =
  (Number(process.env.NEXT_PUBLIC_EVENT_INFLIGHT_STALE_S) || 1800) * 1000;

/**
 * BP19c: derive the pill an event should show from its raw processing_status + photo counts, so
 * the events LIST and the event DETAIL agree. Crucially, a "second batch" — new pending photos
 * on an already-`completed` event — reads as unfinished (not_started) instead of a stale
 * "Completed". Mirrors the detail page's long-standing count-based derivation.
 */
export function derivePillStatus(
  processingStatus: EventProcessingStatus,
  counts: { total: number; pending: number },
): EventProcessingStatus {
  if (processingStatus === "queued" || processingStatus === "processing") {
    return processingStatus; // in-flight — trust the live status
  }
  if (processingStatus === "failed") return "failed"; // terminal, retryable
  // Not in-flight, not failed: reflect outstanding work, not the (possibly stale) status.
  return counts.total > 0 && counts.pending === 0 ? "completed" : "not_started";
}
