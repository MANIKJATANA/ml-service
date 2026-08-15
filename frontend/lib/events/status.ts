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
 * Event-level inference state → tone + label (the FE polls this). Colour arrives only when
 * work is actually happening: not_started/queued stay neutral, processing = info (live),
 * completed = success.
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
  processing: "Processing",
  completed: "Completed",
  failed: "Processing failed",
};
