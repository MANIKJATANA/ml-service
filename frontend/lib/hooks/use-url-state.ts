"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/**
 * Read + write a set of list params in the URL query (BP25, R3-A2-08) so a filtered/sorted list
 * is shareable + survives Back. `get(key, default)` reads `?key=`; `set({...})` writes MANY params
 * in ONE `router.replace(scroll:false)` (so a two-param change like sort+dir can't race itself). A
 * value of "" / null drops the param (clean URLs; the default stays out of the URL).
 *
 * NOTE: a page using this must render inside a `<Suspense>` boundary (useSearchParams bails out
 * of static prerendering otherwise). Reactive to Back/Forward (the URL is the source of truth).
 */
export function useUrlParams() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const get = useCallback(
    (key: string, defaultValue = "") => searchParams.get(key) ?? defaultValue,
    [searchParams],
  );

  const set = useCallback(
    (updates: Record<string, string | null>) => {
      const params = new URLSearchParams(Array.from(searchParams.entries()));
      for (const [key, value] of Object.entries(updates)) {
        if (!value) params.delete(key);
        else params.set(key, value);
      }
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [searchParams, pathname, router],
  );

  return { get, set };
}
