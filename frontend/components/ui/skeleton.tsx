import { cn } from "@/lib/utils";

/** Loading placeholder — size/shape via className. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-button bg-surface-2", className)} aria-hidden="true" />;
}
