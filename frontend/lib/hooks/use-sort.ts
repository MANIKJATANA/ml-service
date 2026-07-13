"use client";

import { useMemo, useState } from "react";

export type SortDir = "asc" | "desc";

/**
 * Client-side list sort over a stable `accessors` map (define it at module scope so the
 * memo stays stable). `toggle(key)` flips direction when the key is already active, else
 * switches to that key ascending. Strings sort with `localeCompare`; numbers numerically.
 */
export function useSort<T>(
  items: T[],
  accessors: Record<string, (item: T) => string | number>,
  initialKey: string,
  initialDir: SortDir = "asc",
) {
  const [sortKey, setSortKey] = useState(initialKey);
  const [sortDir, setSortDir] = useState<SortDir>(initialDir);

  const sorted = useMemo(() => {
    const accessor = accessors[sortKey];
    if (!accessor) return items;
    // Direction-aware compare (not sort-then-reverse) so Array.sort's stability holds
    // in BOTH directions — ties keep their incoming (API) order, e.g. date-less events.
    const sign = sortDir === "desc" ? -1 : 1;
    return [...items].sort((a, b) => {
      const av = accessor(a);
      const bv = accessor(b);
      const cmp =
        typeof av === "string" && typeof bv === "string"
          ? av.localeCompare(bv)
          : av < bv
            ? -1
            : av > bv
              ? 1
              : 0;
      return cmp * sign;
    });
  }, [items, accessors, sortKey, sortDir]);

  function toggle(key: string) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  return { sorted, sortKey, sortDir, toggle };
}
