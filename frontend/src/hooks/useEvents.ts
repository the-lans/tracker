import { useInfiniteQuery } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import type { EventFilters, TrackerEvent } from "@/lib/events.types";

export const EVENTS_PAGE_SIZE = 50;
const EVENTS_REFRESH_MS = 30_000;

/**
 * Раздел 18.4: лента событий, новые сверху; следующая страница — события
 * раньше последнего показанного (`before`).
 */
export function useEvents(filters: EventFilters) {
  return useInfiniteQuery({
    queryKey: ["events", filters],
    queryFn: ({ pageParam }) =>
      api.get<TrackerEvent[]>("/events", {
        audience: filters.audience,
        category: filters.category,
        before: pageParam,
        limit: EVENTS_PAGE_SIZE,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) =>
      lastPage.length < EVENTS_PAGE_SIZE ? undefined : lastPage[lastPage.length - 1]?.created_at,
    refetchInterval: EVENTS_REFRESH_MS,
  });
}
