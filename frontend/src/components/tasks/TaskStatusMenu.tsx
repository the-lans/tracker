import { useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/common/dialogs/ConfirmDialog";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { TaskStatusBadge } from "@/components/tasks/TaskStatusBadge";
import { TASK_STATUS_META } from "@/components/tasks/taskStatusMeta";
import { useChangeTaskStatus } from "@/hooks/useTasks";
import { toastError } from "@/lib/errors";
import { isResettable, manualStatusTargets } from "@/lib/taskStatusTransitions";
import type { Task, TaskStatus } from "@/lib/types";

/**
 * Раздел 14.1: бейдж статуса в шапке задачи — меню ручной смены статуса,
 * если пользователь может её сменить. Возврат из `failed`/`done` сбрасывает
 * прогон и требует подтверждения.
 */
export function TaskStatusMenu({ task }: { task: Task }) {
  const changeStatus = useChangeTaskStatus(task.id);
  const [resetTarget, setResetTarget] = useState<TaskStatus | null>(null);
  const targets = manualStatusTargets(task);

  if (targets.length === 0) return <TaskStatusBadge status={task.status} />;

  function change(toStatus: TaskStatus) {
    changeStatus.mutate(toStatus, {
      onSuccess: () => {
        setResetTarget(null);
        toast.success(`Статус: «${TASK_STATUS_META[toStatus].label}»`);
      },
      onError: toastError("Не удалось сменить статус"),
    });
  }

  function select(value: string) {
    const toStatus = value as TaskStatus;
    if (isResettable(task.status)) setResetTarget(toStatus);
    else change(toStatus);
  }

  return (
    <>
      <Select value={task.status} disabled={changeStatus.isPending} onValueChange={select}>
        <SelectTrigger
          aria-label="Сменить статус задачи"
          className="h-auto w-auto gap-1 rounded-full border-0 bg-transparent p-0"
        >
          <TaskStatusBadge status={task.status} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={task.status} disabled>
            {TASK_STATUS_META[task.status].label}
          </SelectItem>
          {targets.map((status) => (
            <SelectItem key={status} value={status}>
              {TASK_STATUS_META[status].label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <ConfirmDialog
        open={resetTarget !== null}
        onOpenChange={(open) => !open && setResetTarget(null)}
        title={`Перевести задачу в «${resetTarget ? TASK_STATUS_META[resetTarget].label : ""}»?`}
        description="Прогон будет сброшен: можно сменить пайплайн и состав нод, а запуск пройдёт пайплайн с начала в той же сессии агента. История выполнения сохранится."
        confirmLabel="Сбросить прогон"
        pending={changeStatus.isPending}
        onConfirm={() => resetTarget && change(resetTarget)}
      />
    </>
  );
}
