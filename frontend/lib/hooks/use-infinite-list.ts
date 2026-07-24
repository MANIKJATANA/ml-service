"use client";

import { useCallback, useEffect } from "react";
import useSWRInfinite from "swr/infinite";

import type { ListParams } from "@/lib/api/endpoints";
import type { ListPage, SortDir } from "@/lib/api/types";

/** The server-facing controls a list page drives (BP9, decisions/0055). `status` doubles as
 *  the FilterChips selection ("all" -> no filter). */
export interface ListQuery {
  q?: string;
  sort?: string;
  dir?: SortDir;
  status?: string;
}

export const LIST_PAGE_SIZE = 50;

/**
 * Server-paginated infinite list (BP9). Loads one page at a time via `useSWRInfinite`,
 * flattens the pages, and stops requesting once every row is loaded. Reused by every admin
 * list + the event gallery. `keyBase` null disables the fetch (e.g. a gate is off);
 * changing any query field resets to the first page.
 */
export function useInfiniteList<T>(
  keyBase: string | null,
  query: ListQuery,
  fetchPage: (params: ListParams) => Promise<ListPage<T>>,
) {
  const queryKey = JSON.stringify(query);

  const getKey = (index: number, prev: ListPage<T> | null): string | null => {
    if (keyBase === null) return null;
    // Stop once the previous page reached the end (offset + rows >= total).
    if (prev && prev.offset + prev.items.length >= prev.total) return null;
    return `${keyBase}?${queryKey}#${index}`;
  };

  const { data, error, isLoading, isValidating, size, setSize, mutate } =
    useSWRInfinite<ListPage<T>>(
      getKey,
      (key: string) => {
        const index = Number(key.slice(key.lastIndexOf("#") + 1));
        return fetchPage({ ...query, limit: LIST_PAGE_SIZE, offset: index * LIST_PAGE_SIZE });
      },
      { revalidateFirstPage: false, keepPreviousData: true },
    );

  // Any filter/sort/search change collapses back to a single first page.
  useEffect(() => {
    setSize(1);
  }, [queryKey, setSize]);

  const pages = data ?? [];
  const items = pages.flatMap((p) => p.items);
  const total = pages[0]?.total ?? 0;
  const reachedEnd = data !== undefined && items.length >= total;
  // While a not-yet-first load is in flight, or a further page is being fetched.
  const isLoadingMore =
    isLoading || (size > 0 && data !== undefined && data[size - 1] === undefined);

  const loadMore = useCallback(() => {
    setSize((s) => s + 1);
  }, [setSize]);

  return {
    items,
    total,
    error,
    isLoading,
    isValidating,
    reachedEnd,
    isLoadingMore,
    loadMore,
    mutate,
  };
}
