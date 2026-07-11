import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: ReactNode;
  className?: string;
}

/** Page title + optional description and right-aligned actions, over a hairline. */
export function PageHeader({ title, description, actions, className }: PageHeaderProps) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-4 border-b border-hairline pb-4",
        className,
      )}
    >
      <div className="flex flex-col gap-1">
        <h1 className="text-display-md text-ink">{title}</h1>
        {description ? <p className="text-body text-ink-secondary">{description}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}
