import { useMemo, useState } from "react";
import { ListTodo, Plus, Search, SearchX } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { NotificationBell } from "@/components/layout/NotificationBell";
import { TaskCard } from "@/components/tasks/TaskCard";
import { CreateTaskDialog } from "@/components/tasks/CreateTaskDialog";
import { Button } from "@/components/ui/button";
import { useTasks } from "@/hooks/useTasks";
import { TaskStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";

type FilterKey = "all" | "in_progress" | "awaiting" | "done" | "failed";

const FILTERS: { key: FilterKey; label: string; statuses: TaskStatus[] | null }[] = [
  { key: "all", label: "Все", statuses: null },
  { key: "in_progress", label: "В работе", statuses: [TaskStatus.IN_PROGRESS, TaskStatus.PAUSED] },
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
  const [createOpen, setCreateOpen] = useState(false);

  const counts = useMemo(() => {
    const result: Record<FilterKey, number> = {
      all: tasks?.length ?? 0,
      in_progress: 0,
      awaiting: 0,
      done: 0,
      failed: 0,
    };
    for (const task of tasks ?? []) {
      for (const filterDef of FILTERS) {
        if (filterDef.statuses?.includes(task.status)) {
          result[filterDef.key] += 1;
        }
      }
    }
    return result;
  }, [tasks]);

  const filtered = useMemo(() => {
    const activeFilter = FILTERS.find((f) => f.key === filter);
    const searchLower = search.trim().toLowerCase();
    return (tasks ?? []).filter((task) => {
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
  }, [tasks, filter, search]);

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
      </div>

      <div className={PAGE_BODY}>
        {isLoading && <div className="py-10 text-center text-text-3">Загрузка задач…</div>}
        {!isLoading && filtered.length === 0 && ((tasks ?? []).length === 0 ? (
          <EmptyState
            icon={ListTodo}
            title="Задач пока нет"
            hint="Нажмите «+ Новая задача» вверху справа: укажите код задачи (например, RR-12345), название, описание и репозитории. Затем на странице задачи выберите пайплайн и нажмите «Запустить»."
          />
        ) : (
          <EmptyState
            icon={SearchX}
            title="Задачи не найдены"
            hint="Выберите фильтр «Все» или измените текст поиска."
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
