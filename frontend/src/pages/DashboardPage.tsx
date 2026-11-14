import { useMemo, useState } from "react";
import { ListTodo, Plus, Search, SearchX } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { NotificationBell } from "@/components/layout/NotificationBell";
import { TaskCard } from "@/components/tasks/TaskCard";
import { QueueSummaryLine } from "@/components/tasks/QueueSummaryLine";
import { CreateTaskDialog } from "@/components/tasks/CreateTaskDialog";
import { Button } from "@/components/ui/button";
import { FilterSelect } from "@/components/common/filters/FilterSelect";
import { NO_CATEGORY_LABEL } from "@/components/taskCategories/TaskCategorySelect";
import { useTasks } from "@/hooks/useTasks";
import { useTaskCategories } from "@/hooks/useTaskCategories";
import { TaskStatus } from "@/lib/types";
import { PRE_LAUNCH_STATUSES, QUEUE_STATUSES } from "@/lib/taskStatusTransitions";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";

/** Фильтр «Без категории» — задачи, у которых категория не выбрана. */
const WITHOUT_CATEGORY = "none";

type FilterKey = "all" | "pre_launch" | "queue" | "in_progress" | "awaiting" | "done" | "failed";

const FILTERS: { key: FilterKey; label: string; statuses: readonly TaskStatus[] | null }[] = [
  { key: "all", label: "Все", statuses: null },
  { key: "pre_launch", label: "До запуска", statuses: PRE_LAUNCH_STATUSES },
  { key: "queue", label: "В очереди", statuses: QUEUE_STATUSES },
  { key: "in_progress", label: "В работе", statuses: [TaskStatus.IN_PROGRESS, TaskStatus.PAUSED, TaskStatus.AWAITING_LIMIT] },
  {
    key: "awaiting",
    label: "Ждут решения",
    statuses: [TaskStatus.AWAITING_INPUT, TaskStatus.PLAN_REVIEW],
  },
  { key: "done", label: "Завершено", statuses: [TaskStatus.DONE] },
  {
    key: "failed",
    label: "Ошибки",
    statuses: [TaskStatus.FAILED, TaskStatus.REBASE_CONFLICT],
  },
];

export function DashboardPage() {
  const { data: tasks, isLoading } = useTasks();
  const [filter, setFilter] = useState<FilterKey>("all");
  const [search, setSearch] = useState("");
  const [chosenCategory, setChosenCategory] = useState<string | undefined>(undefined);
  const { data: categories } = useTaskCategories();
  const categoryLabels = useMemo<Record<string, string>>(
    () => ({
      [WITHOUT_CATEGORY]: NO_CATEGORY_LABEL,
      ...Object.fromEntries((categories ?? []).map((category) => [category.id, category.name])),
    }),
    [categories],
  );
  // Удалённая категория — снова все задачи, а не пустой фильтр.
  const categoryFilter =
    chosenCategory !== undefined && chosenCategory in categoryLabels ? chosenCategory : undefined;
  const [createOpen, setCreateOpen] = useState(false);

  const categoryTasks = useMemo(
    () =>
      (tasks ?? []).filter((task) => {
        if (categoryFilter === undefined) return true;
        if (categoryFilter === WITHOUT_CATEGORY) return !task.category_id;
        return task.category_id === categoryFilter;
      }),
    [tasks, categoryFilter],
  );

  const counts = useMemo(() => {
    const result: Record<FilterKey, number> = {
      all: categoryTasks.length,
      pre_launch: 0,
      queue: 0,
      in_progress: 0,
      awaiting: 0,
      done: 0,
      failed: 0,
    };
    for (const task of categoryTasks) {
      for (const filterDef of FILTERS) {
        if (filterDef.statuses?.includes(task.status)) {
          result[filterDef.key] += 1;
        }
      }
    }
    return result;
  }, [categoryTasks]);

  const filtered = useMemo(() => {
    const activeFilter = FILTERS.find((f) => f.key === filter);
    const searchLower = search.trim().toLowerCase();
    return categoryTasks.filter((task) => {
      if (activeFilter?.statuses && !activeFilter.statuses.includes(task.status)) return false;
      if (
        searchLower &&
        !task.code.toLowerCase().includes(searchLower) &&
        !task.title.toLowerCase().includes(searchLower)
      ) {
        return false;
      }
      return true;
    });
  }, [categoryTasks, filter, search]);

  return (
    <div className={PAGE_ROOT}>
      <PageHeader
        title="Дашборд"
        actions={
          <>
            <label className="hidden min-h-11 items-center gap-2 rounded-md border border-border bg-surface-2 px-3 text-body-lg text-text-3 md:flex">
              <Search className="size-4" />
              <input
                aria-label="Найти задачу по коду или названию"
                className="h-11 w-56 bg-transparent outline-none placeholder:text-text-3"
                placeholder="Код или название задачи..."
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            <NotificationBell />
            <Button aria-label="Новая задача" onClick={() => setCreateOpen(true)}>
              <Plus className="size-4" />
              <span className="hidden sm:inline">Новая задача</span>
            </Button>
          </>
        }
      />

      <QueueSummaryLine />
      <div className="flex flex-wrap items-center gap-2 px-5 pb-4 lg:px-8">
        {FILTERS.map((filterDef) => (
          <button
            key={filterDef.key}
            type="button"
            onClick={() => setFilter(filterDef.key)}
            className={cn(
              "touch-target rounded-full bg-surface-2 px-3.5 py-1.5 text-body font-bold text-text",
              filter === filterDef.key && "bg-text text-bg",
            )}
          >
            {filterDef.label} · {counts[filterDef.key]}
          </button>
        ))}
        <FilterSelect
          value={categoryFilter}
          onChange={setChosenCategory}
          values={[WITHOUT_CATEGORY, ...(categories ?? []).map((category) => category.id)]}
          labels={categoryLabels}
          allLabel="Все категории"
          label="Категория"
          className="w-48"
        />
      </div>

      <div className={PAGE_BODY}>
        {isLoading && <div className="py-10 text-center text-text-3">Загрузка задач…</div>}
        {!isLoading && filtered.length === 0 && ((tasks ?? []).length === 0 ? (
          <EmptyState
            icon={ListTodo}
            title="Задач пока нет"
            hint="Нажмите «+ Новая задача» вверху справа: укажите код задачи (например, RR-12345), название, описание и репозитории. Затем на странице задачи выберите пайплайн и нажмите «Запустить» или поставьте задачу в очередь статусом «Готова к реализации»."
          />
        ) : (
          <EmptyState
            icon={SearchX}
            title="Задачи не найдены"
            hint="Выберите фильтр «Все», «Все категории» или измените текст поиска."
          />
        ))}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {filtered.map((task) => (
            <TaskCard key={task.id} task={task} />
          ))}
        </div>
      </div>

      <CreateTaskDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
