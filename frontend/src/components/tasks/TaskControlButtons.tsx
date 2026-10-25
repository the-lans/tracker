import { useState } from "react";
import { Ban, Pause, Play, RotateCcw, Square } from "lucide-react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/common/dialogs/ConfirmDialog";
import { HEADER_BUTTON } from "@/styles/classes";
import { TaskLifecycleActions } from "@/components/tasks/TaskLifecycleActions";
import {
  useCancelQueuedTask,
  usePauseTask,
  useRestartTask,
  useStartTask,
  useResumeTask,
  useStopTask,
} from "@/hooks/useTasks";
import { toastError } from "@/lib/errors";
import { cn } from "@/lib/utils";
import { TaskStatus, type Task } from "@/lib/types";
import { ButtonLabel } from "@/components/common/actions/ButtonLabel";

/** Раздел 14.2: действия пользователя, доступные в текущем статусе задачи. */
export function TaskControlButtons({ task }: { task: Task }) {
  const [stopConfirmOpen, setStopConfirmOpen] = useState(false);
  const pauseTask = usePauseTask(task.id);
  const resumeTask = useResumeTask(task.id);
  const stopTask = useStopTask(task.id);
  const cancelTask = useCancelQueuedTask(task.id);
  const restartTask = useRestartTask(task.id);
  const startTask = useStartTask(task.id);
  const canStop = task.status === TaskStatus.IN_PROGRESS || task.status === TaskStatus.PAUSED;

  function handleStop() {
    stopTask.mutate(undefined, {
      onSuccess: () => {
        setStopConfirmOpen(false);
        toast.success("Задача останавливается");
      },
      onError: toastError("Не удалось остановить задачу"),
    });
  }

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {/* Раздел 14.2: запуск новой задачи — прямо со страницы, где её настраивают. */}
      {task.status === TaskStatus.NEW && (
        <button
          type="button"
          className={cn(HEADER_BUTTON, task.pipeline_id && "border-accent bg-accent text-on-accent")}
          aria-label="Запустить задачу"
          title={task.pipeline_id ? "Запустить задачу" : "Сначала выберите пайплайн на вкладке «Обзор»"}
          disabled={!task.pipeline_id || startTask.isPending}
          onClick={() =>
            startTask.mutate(undefined, {
              onSuccess: () => toast.success("Задача поставлена в очередь"),
              onError: toastError("Не удалось запустить задачу"),
            })
          }
        >
          <Play className="size-3.5" />
          <ButtonLabel>Запустить</ButtonLabel>
        </button>
      )}
      {task.status === TaskStatus.QUEUED && (
        <button
          type="button"
          className={HEADER_BUTTON}
          aria-label="Отменить запуск"
          title="Отменить запуск"
          disabled={cancelTask.isPending}
          onClick={() =>
            cancelTask.mutate(undefined, {
              onSuccess: () => toast.success("Запуск отменён, автозапуск выключен"),
              onError: toastError("Не удалось отменить запуск"),
            })
          }
        >
          <Ban className="size-3.5" />
          <ButtonLabel>Отменить запуск</ButtonLabel>
        </button>
      )}
      {task.status === TaskStatus.IN_PROGRESS && (
        <button
          type="button"
          className={HEADER_BUTTON}
          aria-label="Приостановить"
          title="Приостановить"
          disabled={pauseTask.isPending}
          onClick={() =>
            pauseTask.mutate(undefined, {
              onSuccess: () => toast.success("Пауза наступит после текущей ноды"),
              onError: toastError("Не удалось приостановить задачу"),
            })
          }
        >
          <Pause className="size-3.5" />
          <ButtonLabel>Приостановить</ButtonLabel>
        </button>
      )}
      {task.status === TaskStatus.PAUSED && (
        <button
          type="button"
          className={HEADER_BUTTON}
          aria-label="Продолжить"
          title="Продолжить"
          disabled={resumeTask.isPending}
          onClick={() =>
            resumeTask.mutate(undefined, {
              onSuccess: () => toast.success("Задача продолжает выполнение"),
              onError: toastError("Не удалось продолжить задачу"),
            })
          }
        >
          <Play className="size-3.5" />
          <ButtonLabel>Продолжить</ButtonLabel>
        </button>
      )}
      {canStop && (
        <button
          type="button"
          className={HEADER_BUTTON}
          aria-label="Остановить"
          title="Остановить"
          onClick={() => setStopConfirmOpen(true)}
        >
          <Square className="size-3.5" />
          <ButtonLabel>Остановить</ButtonLabel>
        </button>
      )}
      {task.status === TaskStatus.FAILED && (
        <button
          type="button"
          className={HEADER_BUTTON}
          aria-label="Перезапустить с текущей ноды"
          title="Перезапустить с текущей ноды"
          disabled={restartTask.isPending}
          onClick={() =>
            restartTask.mutate(undefined, {
              onSuccess: () => toast.success("Задача перезапускается с упавшей ноды"),
              onError: toastError("Не удалось перезапустить"),
            })
          }
        >
          <RotateCcw className="size-3.5" />
          <ButtonLabel>Перезапустить с текущей ноды</ButtonLabel>
        </button>
      )}

      <TaskLifecycleActions task={task} />

      <ConfirmDialog
        open={stopConfirmOpen}
        onOpenChange={setStopConfirmOpen}
        title="Остановить задачу?"
        description="Текущее обращение к сессии будет прервано, задача перейдёт в статус «Ошибка». Продолжить можно кнопкой «Перезапустить с текущей ноды»."
        confirmLabel="Остановить"
        danger
        pending={stopTask.isPending}
        onConfirm={handleStop}
      />
    </div>
  );
}
