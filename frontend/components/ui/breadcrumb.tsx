import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { Fragment } from "react";

import { cn } from "@/lib/utils";

interface Crumb {
  label: string;
  href?: string;
}

/** Breadcrumb trail; the last item is the current page (no link). */
export function Breadcrumb({ items, className }: { items: Crumb[]; className?: string }) {
  return (
    <nav aria-label="Breadcrumb" className={cn("flex items-center gap-1.5 text-body-sm", className)}>
      {items.map((item, i) => {
        const last = i === items.length - 1;
        return (
          <Fragment key={item.href ?? item.label}>
            {item.href && !last ? (
              <Link
                href={item.href}
                className="rounded text-ink-secondary transition-colors hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {item.label}
              </Link>
            ) : (
              <span
                className={last ? "font-medium text-ink" : "text-ink-secondary"}
                aria-current={last ? "page" : undefined}
              >
                {item.label}
              </span>
            )}
            {!last ? <ChevronRight className="size-3.5 text-ink-muted" aria-hidden="true" /> : null}
          </Fragment>
        );
      })}
    </nav>
  );
}
