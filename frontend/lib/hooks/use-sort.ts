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

/**
 * Like {@link useListSort}, but the sort key + direction live in the URL (BP25) — shareable +
 * Back-safe. Takes a `useUrlParams()` bag so sort + dir change in ONE atomic `set` (no race).
 * The default sort stays out of the URL until the user sorts.
 */
export function useUrlListSort(
  initialKey: string,
  defaultDirs: Record<string, SortDir>,
  params: { get: (k: string, d?: string) => string; set: (u: Record<string, string | null>) => void },
) {
  const sort = params.get("sort", initialKey);
  const dir: SortDir = params.get("dir", defaultDirs[sort] ?? "asc") === "desc" ? "desc" : "asc";

  function onSort(key: string) {
    if (key === sort) {
      params.set({ dir: dir === "asc" ? "desc" : "asc" });
    } else {
      params.set({ sort: key, dir: defaultDirs[key] ?? "asc" });
    }
  }

  return { sort, dir, onSort };
}
