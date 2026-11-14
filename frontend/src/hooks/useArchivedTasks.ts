import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { taskKeys } from "@/hooks/useTasks";
import { api } from "@/lib/apiClient";
import type { ArchiveFilters, ArchivedTaskPage } from "@/lib/archive.types";
import { localDayBoundary } from "@/lib/utils";

export const ARCHIVE_PAGE_SIZE = 20;

/**
 * Раздел 15.1: страница архива. Пока грузится следующая, видна прежняя —
 * список не мигает при листании и вводе поиска.
 */
export function useArchivedTasks(filters: ArchiveFilters) {
  return useQuery({
    queryKey: taskKeys.archive(filters),
    queryFn: () =>
      api.get<ArchivedTaskPage>("/tasks/archive", {
        search: filters.search.trim() || undefined,
        finished_from: localDayBoundary(filters.from, false),
        finished_to: localDayBoundary(filters.to, true),
        page: filters.page,
        page_size: ARCHIVE_PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
  });
}
