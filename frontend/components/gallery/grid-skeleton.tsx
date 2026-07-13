import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** Placeholder masonry shown while a photo grid loads (decisions/0035). */
export function GridSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading photos"
      className="columns-2 gap-2 sm:columns-3 lg:columns-4 [&>*]:mb-2 [&>*]:break-inside-avoid"
    >
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <Skeleton key={i} className={cn("w-full rounded-card", i % 2 ? "h-48" : "h-64")} />
      ))}
    </div>
  );
}
