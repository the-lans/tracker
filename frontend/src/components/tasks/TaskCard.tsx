import { Link } from "react-router-dom";
import { Play } from "lucide-react";
import { toast } from "sonner";
import { TaskDayMarks } from "@/components/tasks/TaskDayMarks";
import { TaskStatusBadge } from "@/components/tasks/TaskStatusBadge";
import { TASK_STATUS_META } from "@/components/tasks/taskStatusMeta";
import { useLlmLimit, useStartTask } from "@/hooks/useTasks";
import { launchWaitHint } from "@/lib/llmAccounts";
import { formatRelativeShort } from "@/lib/utils";
import { errorMessage } from "@/lib/errors";
import { TaskStatus, type Task } from "@/lib/types";
import { OwnerLabel } from "@/components/common/avatar/OwnerLabel";
import { isPreLaunch } from "@/lib/taskStatusTransitions";

/** Раздел 14.4: приоритет очереди по умолчанию — на карточке не показывается. */
const DEFAULT_QUEUE_PRIORITY = 100;

export function TaskCard({ task }: { task: Task }) {
  const meta = TASK_STATUS_META[task.status];
  const startTask = useStartTask(task.id);
  const preLaunch = isPreLaunch(task.status);
  const { data: llmLimit } = useLlmLimit(task.created_by, preLaunch);
  const launchTitle = !task.pipeline_id
    ? "Сначала выберите пайплайн на странице задачи"
    : llmLimit?.wait_until
      ? launchWaitHint(llmLimit.wait_until)
      : "Запустить задачу";

  const subtitle =
    isPreLaunch(task.status) && !task.pipeline_id
      ? "Пайплайн не выбран"
      : task.queue_position !== null
        ? `№${task.queue_position} в очереди`
      : task.status === TaskStatus.FAILED && task.last_failed_order_index !== null
        ? `Сбой на ноде №${task.last_failed_order_index + 1}`
        : task.status === TaskStatus.QUEUED && task.scheduled_start_at
          ? `старт в ${new Date(task.scheduled_start_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}`
          : null;

  return (
    <div
      className="flex flex-col gap-2.5 rounded-lg border-[1.5px] bg-surface p-4"
      style={{ borderColor: meta.borderVar }}
    >
      <div className="flex items-center gap-2">
        <Link to={`/tasks/${task.id}`} className="touch-hit font-mono text-meta font-bold text-text-3">
          {task.code}
        </Link>
        <div className="ml-auto flex items-center gap-1.5">
          {task.queue_priority !== DEFAULT_QUEUE_PRIORITY && (
            <span className="text-caption font-bold text-text-3" title="Приоритет в очереди">
              P{task.queue_priority}
            </span>
          )}
          <TaskStatusBadge status={task.status} />
        </div>
      </div>
      <Link
        to={`/tasks/${task.id}`}
        className="min-h-11 text-card-title font-bold leading-snug text-text"
      >
        {task.title}
      </Link>
      {subtitle && <div className="text-xs text-text-3">{subtitle}</div>}
      <OwnerLabel ownerId={task.created_by} />
      <div className="mt-0.5 flex items-center gap-2 border-t border-border pt-2.5">
        <span className="text-xs font-bold text-text-2">{formatRelativeShort(task.updated_at)}</span>
        <TaskDayMarks task={task} />
        {preLaunch && (
          <button
            type="button"
            className="ml-auto flex touch-target size-[30px] items-center justify-center rounded-[9px] border border-accent-border bg-accent-tint text-accent disabled:opacity-50"
            aria-label="Запустить задачу"
            title={launchTitle}
            disabled={!task.pipeline_id || task.chat_active || startTask.isPending}
            onClick={(event) => {
              event.preventDefault();
              startTask.mutate(undefined, {
                onError: (error) => {
                  toast.error(errorMessage(error, "Не удалось запустить"));
                },
              });
            }}
          >
            <Play className="size-3" fill="currentColor" />
          </button>
        )}
      </div>
    </div>
  );
}
