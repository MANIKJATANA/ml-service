"use client";

import { useState } from "react";

import type { SortDir } from "@/lib/api/types";

/**
 * Server-list sort state (BP9, decisions/0055): the active sort key + direction a paginated
 * list page feeds to its data hook. `onSort(key)` toggles direction when the key is already
 * active, else switches to it using `defaultDirs[key]` (names A→Z, counts most-first). The
 * initial direction is `defaultDirs[initialKey]`.
 */
export function useListSort(initialKey: string, defaultDirs: Record<string, SortDir>) {
  const [sort, setSort] = useState(initialKey);
  const [dir, setDir] = useState<SortDir>(defaultDirs[initialKey] ?? "asc");

  function onSort(key: string) {
    if (key === sort) {
      setDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSort(key);
      setDir(defaultDirs[key] ?? "asc");
    }
  }

  return { sort, dir, onSort };
}
