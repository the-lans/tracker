import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { useActiveCeleryTasks } from "@/hooks/useAdmin";
import { formatDateTime } from "@/lib/utils";

/** Раздел 15.5: активные Celery-задачи по всем пользователям — по ответу воркеров. */
export function CeleryTasksSection() {
  const { data: tasks, isLoading, isError } = useActiveCeleryTasks();

  return (
    <section className="flex flex-col gap-2">
      <div className="text-[12.5px] font-extrabold text-text-2">Активные Celery-задачи</div>
      {isLoading && <div className="text-text-3">Загрузка…</div>}
      {isError && <div className="text-danger-text">Не удалось опросить воркеры</div>}
      {(tasks ?? []).map((task) => (
        <Card key={task.celery_task_id} className="flex items-center gap-3 py-2.5">
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-bold">{task.name}</div>
            <div className="mt-0.5 text-[11px] text-text-3">
              {task.worker} · с {formatDateTime(task.started_at)}
            </div>
          </div>
          {task.task_id && (
            <Link to={`/tasks/${task.task_id}`} className="font-mono text-[12px] font-bold text-accent">
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
