import { useCallback, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { Archive } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { ArchiveFiltersBar } from "@/components/archive/ArchiveFiltersBar";
import { ArchivedTaskRow } from "@/components/archive/ArchivedTaskRow";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { QueryState } from "@/components/common/feedback/QueryState";
import { Pagination } from "@/components/common/navigation/Pagination";
import { ARCHIVE_PAGE_SIZE, useArchivedTasks } from "@/hooks/useArchivedTasks";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useProfile } from "@/hooks/useProfile";
import { pageCountOf, plural } from "@/lib/utils";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";

export const ARCHIVE_SEARCH_DELAY_MS = 300;
const TASK_FORMS: [string, string, string] = ["задача", "задачи", "задач"];
const DAY_FORMS: [string, string, string] = ["день", "дня", "дней"];
/** Параметры адреса: фильтр и страница переживают обновление и «Назад». */
const PARAM = { search: "q", from: "from", to: "to", page: "page" } as const;

function pageFrom(params: URLSearchParams): number {
  const page = Number(params.get(PARAM.page));
  return Number.isInteger(page) && page > 1 ? page : 1;
}

function emptyHint(archiveAfterDays: number | null | undefined): string {
  if (archiveAfterDays === null) return "Автоархивация выключена — срок задаёт администратор.";
  if (archiveAfterDays === undefined) return "Сюда попадают задачи в «Готово» и «Ошибка».";
  return `Задачи в «Готово» и «Ошибка» попадают сюда через ${archiveAfterDays} ${plural(archiveAfterDays, DAY_FORMS)} после завершения.`;
}

/**
 * Раздел 15.1: «Архив» — постраничный список архивных задач (свои,
 * администратору — все) с поиском по коду и названию и периодом завершения.
 */
export function ArchivePage() {
  const [params, setParams] = useSearchParams();
  const search = params.get(PARAM.search) ?? "";
  const from = params.get(PARAM.from) ?? "";
  const to = params.get(PARAM.to) ?? "";
  const page = pageFrom(params);
  // В адрес поиск пишется сразу, а запрос уходит после паузы во вводе.
  const debouncedSearch = useDebouncedValue(search, ARCHIVE_SEARCH_DELAY_MS);
  const { data, isLoading, isError } = useArchivedTasks({ search: debouncedSearch, from, to, page });
  const { data: profile } = useProfile();

  /** Смена отбора возвращает на первую страницу. */
  const update = useCallback(
    (patch: Partial<Record<keyof typeof PARAM, string>>) =>
      setParams(
      (current) => {
        const next = new URLSearchParams(current);
        for (const [key, value] of Object.entries(patch)) {
          const name = PARAM[key as keyof typeof PARAM];
          if (value) next.set(name, value);
          else next.delete(name);
        }
        if (!("page" in patch)) next.delete(PARAM.page);
        return next;
      },
      { replace: true },
    ),
    [setParams],
  );

  // Страница за концом списка (ссылка из закладок, список сократился) — последняя.
  const lastPage = data ? pageCountOf(data.total, ARCHIVE_PAGE_SIZE) : page;
  useEffect(() => {
    if (page > lastPage) update({ page: lastPage > 1 ? String(lastPage) : "" });
  }, [page, lastPage, update]);

  const filtered = Boolean(search || from || to);
  const items = data?.items ?? [];

  return (
    <div className={PAGE_ROOT}>
      <PageHeader title="Архив" />
      <div className={PAGE_BODY}>
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-3">
          <ArchiveFiltersBar
            value={{ search, from, to }}
            onChange={update}
            onReset={() => update({ search: "", from: "", to: "" })}
          />
          <QueryState isLoading={isLoading} isError={isError} errorLabel="Не удалось загрузить архив">
            {data && data.total > 0 && (
              <div className="text-small text-text-3">
                {data.total} {plural(data.total, TASK_FORMS)}
              </div>
            )}
            {items.length === 0 ? (
              filtered ? (
                <EmptyState icon={Archive} title="Ничего не найдено" hint="Измените поиск или период." />
              ) : (
                <EmptyState icon={Archive} title="В архиве пусто" hint={emptyHint(profile?.archive_after_days)} />
              )
            ) : (
              <ul className="flex flex-col gap-2" aria-label="Задачи в архиве">
                {items.map((task) => (
                  <ArchivedTaskRow key={task.id} task={task} />
                ))}
              </ul>
            )}
            {data && (
              <Pagination
                page={page}
                pageSize={ARCHIVE_PAGE_SIZE}
                total={data.total}
                onPageChange={(next) => update({ page: next > 1 ? String(next) : "" })}
              />
            )}
          </QueryState>
        </div>
      </div>
    </div>
  );
}
