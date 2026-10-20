import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { useActiveCeleryTasks } from "@/hooks/useAdmin";
import { formatDateTime } from "@/lib/utils";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { SectionTitle } from "@/components/common/typography/SectionTitle";

/** Раздел 15.5: активные Celery-задачи по всем пользователям — по ответу воркеров. */
export function CeleryTasksSection() {
  const { data: tasks, isLoading, isError } = useActiveCeleryTasks();

  return (
    <section className="flex flex-col gap-2">
      <SectionTitle>Активные Celery-задачи</SectionTitle>
      {isLoading && <LoadingState />}
      {isError && <div className="text-danger-text">Не удалось опросить воркеры</div>}
      {(tasks ?? []).map((task) => (
        <Card key={task.celery_task_id} className="flex items-center gap-3 py-2.5">
          <div className="min-w-0 flex-1">
            <div className="truncate text-body font-bold" title={task.name}>
              {task.name}
            </div>
            <div className="mt-0.5 text-caption text-text-3">
              {task.worker} · с {formatDateTime(task.started_at)}
            </div>
          </div>
          {task.task_id && (
            <Link to={`/tasks/${task.task_id}`} className="touch-target inline-flex shrink-0 items-center justify-end font-mono text-small font-bold text-accent">
              {task.task_code ?? task.task_id.slice(0, 8)}
            </Link>
          )}
        </Card>
      ))}
      {!isLoading && !isError && (tasks ?? []).length === 0 && (
        <div className="py-3 text-center text-text-3">Воркеры сейчас ничего не выполняют</div>
      )}
    </section>
  );
}
