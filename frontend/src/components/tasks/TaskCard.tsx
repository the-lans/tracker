import { Link } from "react-router-dom";
import { Play } from "lucide-react";
import { toast } from "sonner";
import { TaskStatusBadge } from "@/components/tasks/TaskStatusBadge";
import { TASK_STATUS_META } from "@/components/tasks/taskStatusMeta";
import { useStartTask } from "@/hooks/useTasks";
import { formatRelativeShort } from "@/lib/utils";
import { ApiError } from "@/lib/apiClient";
import { TaskStatus, type Task } from "@/lib/types";

export function TaskCard({ task }: { task: Task }) {
  const meta = TASK_STATUS_META[task.status];
  const startTask = useStartTask(task.id);

  const subtitle =
    task.status === TaskStatus.NEW && !task.pipeline_id
      ? "Пайплайн не выбран"
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
        <Link to={`/tasks/${task.id}`} className="font-mono text-[11.5px] font-bold text-text-3">
          {task.code}
        </Link>
        <div className="ml-auto">
          <TaskStatusBadge status={task.status} />
        </div>
      </div>
      <Link
        to={`/tasks/${task.id}`}
        className="min-h-[38px] text-[14.5px] font-bold leading-snug text-text"
      >
        {task.title}
      </Link>
      {subtitle && <div className="text-xs text-text-3">{subtitle}</div>}
      <div className="mt-0.5 flex items-center gap-2 border-t border-border pt-2.5">
        <span className="text-xs font-bold text-text-2">{formatRelativeShort(task.updated_at)}</span>
        {task.status === TaskStatus.NEW && (
          <button
            type="button"
            className="ml-auto flex touch-target size-[30px] items-center justify-center rounded-[9px] border border-accent-border bg-accent-tint text-accent"
            aria-label="Выполнить"
            disabled={startTask.isPending}
            onClick={(event) => {
              event.preventDefault();
              startTask.mutate(undefined, {
                onError: (error) => {
                  toast.error(error instanceof ApiError ? error.message : "Не удалось запустить");
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
