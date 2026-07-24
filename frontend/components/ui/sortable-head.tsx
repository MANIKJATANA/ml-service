"use client";

import { ChevronDown, ChevronsUpDown, ChevronUp } from "lucide-react";

import type { SortDir } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { TableHead } from "./table";

/** A sortable column header: clicking toggles sort on `sortKey`. Shows the active
 *  direction (or a neutral glyph) and sets `aria-sort` for assistive tech. */
export function SortableHead({
  label,
  sortKey,
  activeKey,
  dir,
  onSort,
  className,
}: {
  label: string;
  sortKey: string;
  activeKey: string;
  dir: SortDir;
  onSort: (key: string) => void;
  className?: string;
}) {
  const active = sortKey === activeKey;
  return (
    <TableHead
      className={className}
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cn(
          "inline-flex items-center gap-1 rounded transition-colors hover:text-ink",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          active && "text-ink",
        )}
      >
        {label}
        {active ? (
          dir === "asc" ? (
            <ChevronUp className="size-3.5" aria-hidden="true" />
          ) : (
            <ChevronDown className="size-3.5" aria-hidden="true" />
          )
        ) : (
          <ChevronsUpDown className="size-3.5 opacity-40" aria-hidden="true" />
        )}
      </button>
    </TableHead>
  );
}
