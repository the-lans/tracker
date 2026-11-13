import type { TaskStatus } from "@/lib/types";

/** Раздел 15.1: строка раздела «Архив». */
export interface ArchivedTask {
  id: string;
  code: string;
  title: string;
  /** Итоговый статус до архива — `done` или `failed`. */
  archived_from_status: TaskStatus | null;
  category_name: string | null;
  finished_at: string | null;
  archived_at: string | null;
  repo_cleaned_at: string | null;
  created_by: string;
}

export interface ArchivedTaskPage {
  items: ArchivedTask[];
  total: number;
  page: number;
  page_size: number;
}

/** Отбор раздела — как в адресе страницы: даты в формате `<input type="date">`. */
export interface ArchiveFilters {
  search: string;
  from: string;
  to: string;
  page: number;
}
