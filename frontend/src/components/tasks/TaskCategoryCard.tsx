import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { TaskCategorySelect } from "@/components/taskCategories/TaskCategorySelect";
import { useTaskCategories } from "@/hooks/useTaskCategories";
import { isPreLaunch } from "@/lib/taskStatusTransitions";
import type { Task, TaskUpdateRequest } from "@/lib/types";

/**
 * Раздел 15.7: категория задачи меняется в любом статусе — из категорий автора
 * задачи. Задаче до запуска без пайплайна достаётся пайплайн категории.
 */
export function TaskCategoryCard({
  task,
  pending,
  onUpdate,
}: {
  task: Task;
  pending: boolean;
  onUpdate: (body: TaskUpdateRequest) => void;
}) {
  const { data: categories } = useTaskCategories(task.created_by);
  const fillsPipeline = isPreLaunch(task.status) && task.pipeline_id === null;

  return (
    <Card>
      <div className="text-body font-bold">Категория</div>
      <div className="mt-2">
        <TaskCategorySelect
          value={task.category_id ?? null}
          categories={categories ?? []}
          disabled={pending}
          onChange={(categoryId) => onUpdate({ category_id: categoryId })}
        />
      </div>
      <div className="mt-1 text-meta text-text-3">
        {fillsPipeline
          ? "Пайплайна у задачи нет — его подставит выбранная категория, если он в ней задан."
          : "Меняет только категорию: настройки у задачи уже свои."}{" "}
        <Link to="/categories" className="text-accent hover:underline">
          Категории
        </Link>
      </div>
    </Card>
  );
}
