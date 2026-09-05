import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** Placeholder shown while a photo grid loads (decisions/0035). Mirrors the real grid — a
 *  uniform square tile grid; `variant` only matches the corner radius + gutter ("grid" staff
 *  vs "masonry" student, BP3) so nothing pops when real tiles resolve. */
export function GridSkeleton({ variant = "grid" }: { variant?: "grid" | "masonry" }) {
  const masonry = variant === "masonry";
  return (
    <div
      role="status"
      aria-label="Loading photos"
      className={cn(
        "grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4",
        masonry ? "gap-3" : "gap-2",
      )}
    >
      {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
        <Skeleton
          key={i}
          className={cn("aspect-square w-full", masonry ? "rounded-2xl" : "rounded-card")}
        />
      ))}
    </div>
  );
}
