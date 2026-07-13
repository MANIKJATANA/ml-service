import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** Placeholder masonry shown while a photo grid loads (decisions/0035). `variant` matches
 *  the grid it stands in for — "grid" (staff, square-ish) or "masonry" (student, BP3), so
 *  the corner radius + gutter don't pop when real tiles resolve. */
export function GridSkeleton({ variant = "grid" }: { variant?: "grid" | "masonry" }) {
  const masonry = variant === "masonry";
  return (
    <div
      role="status"
      aria-label="Loading photos"
      className={cn(
        "columns-2 sm:columns-3 lg:columns-4 [&>*]:break-inside-avoid",
        masonry ? "gap-3 [&>*]:mb-3" : "gap-2 [&>*]:mb-2",
      )}
    >
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <Skeleton
          key={i}
          className={cn(
            "w-full",
            masonry ? "rounded-2xl" : "rounded-card",
            i % 2 ? "h-48" : "h-64",
          )}
        />
      ))}
    </div>
  );
}
