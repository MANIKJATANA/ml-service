import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/** A surface panel: white card, hairline border, soft shadow. Add padding at the call site. */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-card border border-hairline bg-canvas shadow-sm", className)}
      {...props}
    />
  );
}
