"use client";

import type { ReactNode } from "react";

import { useDocumentTitle } from "@/lib/hooks/use-document-title";
import { cn } from "@/lib/utils";

interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: ReactNode;
  className?: string;
}

/** Page title + optional description and right-aligned actions, over a hairline. BP25: it also
 *  sets the browser tab title to "{title} · Photos", so every page with a header is named. */
export function PageHeader({ title, description, actions, className }: PageHeaderProps) {
  useDocumentTitle(title);
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
