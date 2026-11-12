import { Card } from "@/components/ui/card";
import { useActiveCeleryTasks } from "@/hooks/useAdmin";
import { formatDateTime } from "@/lib/utils";
import { QueryState } from "@/components/common/feedback/QueryState";
import { SectionTitle } from "@/components/common/typography/SectionTitle";
import { TaskCodeLink } from "@/components/tasks/TaskCodeLink";

/** Раздел 15.5: активные Celery-задачи по всем пользователям — по ответу воркеров. */
export function CeleryTasksSection() {
  const { data: tasks, isLoading, isError } = useActiveCeleryTasks();

  return (
    <section className="flex flex-col gap-2">
      <SectionTitle>Активные Celery-задачи</SectionTitle>
      <QueryState isLoading={isLoading} isError={isError} errorLabel="Не удалось опросить воркеры">
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
              <TaskCodeLink taskId={task.task_id} code={task.task_code} className="shrink-0 justify-end" />
            )}
          </Card>
        ))}
        {(tasks ?? []).length === 0 && (
          <div className="py-3 text-center text-text-3">Воркеры сейчас ничего не выполняют</div>
        )}
      </QueryState>
    </section>
  );
}
