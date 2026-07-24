"use client";

import { useEffect, useState } from "react";

/** Debounce a rapidly-changing value (BP9) — used so a search box hits the server only
 *  after the user pauses typing, not on every keystroke. */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}
