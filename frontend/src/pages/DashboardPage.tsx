import { useMemo, useState } from "react";
import { Plus, Search } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { NotificationBell } from "@/components/layout/NotificationBell";
import { TaskCard } from "@/components/tasks/TaskCard";
import { CreateTaskDialog } from "@/components/tasks/CreateTaskDialog";
import { Button } from "@/components/ui/button";
import { useTasks } from "@/hooks/useTasks";
import { TaskStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

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
    <div className="flex h-full flex-col">
      <PageHeader
        title="Дашборд"
        actions={
          <>
            <div className="hidden items-center gap-2 rounded-md border border-border bg-surface-2 px-3 py-2 text-[13.5px] text-text-3 md:flex">
              <Search className="size-4" />
              <input
                className="w-56 bg-transparent outline-none placeholder:text-text-3"
                placeholder="Найти задачу по коду..."
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
            <NotificationBell />
            <Button onClick={() => setCreateOpen(true)}>
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
              "touch-target rounded-full bg-surface-2 px-3.5 py-1.5 text-[13px] font-bold text-text",
              filter === filterDef.key && "bg-text text-white",
            )}
          >
            {filterDef.label} · {counts[filterDef.key]}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-5 pb-8 lg:px-8">
        {isLoading && <div className="py-10 text-center text-text-3">Загрузка задач…</div>}
        {!isLoading && filtered.length === 0 && (
          <div className="py-10 text-center text-text-3">Задачи не найдены</div>
        )}
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
