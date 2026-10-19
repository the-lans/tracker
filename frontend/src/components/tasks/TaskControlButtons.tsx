import { useState } from "react";
import { Ban, Pause, Play, RotateCcw, Square } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useCancelQueuedTask,
  usePauseTask,
  useRestartTask,
  useResumeTask,
  useStopTask,
} from "@/hooks/useTasks";
import { ApiError } from "@/lib/apiClient";
import { TaskStatus, type Task } from "@/lib/types";

const HEADER_BUTTON =
  "flex touch-target items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-[13px] font-bold text-text-2 disabled:opacity-50";

function onError(fallback: string) {
  return (error: Error) => toast.error(error instanceof ApiError ? error.message : fallback);
}

/** Раздел 14.2: действия пользователя, доступные в текущем статусе задачи. */
export function TaskControlButtons({ task }: { task: Task }) {
  const [stopConfirmOpen, setStopConfirmOpen] = useState(false);
  const pauseTask = usePauseTask(task.id);
  const resumeTask = useResumeTask(task.id);
  const stopTask = useStopTask(task.id);
  const cancelTask = useCancelQueuedTask(task.id);
  const restartTask = useRestartTask(task.id);
  const canStop = task.status === TaskStatus.IN_PROGRESS || task.status === TaskStatus.PAUSED;

  function handleStop() {
    stopTask.mutate(undefined, {
      onSuccess: () => {
        setStopConfirmOpen(false);
        toast.success("Задача останавливается");
      },
      onError: onError("Не удалось остановить задачу"),
    });
  }

  return (
    <div className="ml-auto flex items-center gap-2">
      {task.status === TaskStatus.QUEUED && (
        <button
          type="button"
          className={HEADER_BUTTON}
          disabled={cancelTask.isPending}
          onClick={() =>
            cancelTask.mutate(undefined, {
              onSuccess: () => toast.success("Запуск отменён, автозапуск выключен"),
              onError: onError("Не удалось отменить запуск"),
            })
          }
        >
          <Ban className="size-3.5" />
          <span className="hidden sm:inline">Отменить запуск</span>
        </button>
      )}
      {task.status === TaskStatus.IN_PROGRESS && (
        <button
          type="button"
          className={HEADER_BUTTON}
          disabled={pauseTask.isPending}
          onClick={() =>
            pauseTask.mutate(undefined, {
              onSuccess: () => toast.success("Пауза наступит после текущей ноды"),
              onError: onError("Не удалось приостановить задачу"),
            })
          }
        >
          <Pause className="size-3.5" />
          <span className="hidden sm:inline">Приостановить</span>
        </button>
      )}
      {task.status === TaskStatus.PAUSED && (
        <button
          type="button"
          className={HEADER_BUTTON}
          disabled={resumeTask.isPending}
          onClick={() =>
            resumeTask.mutate(undefined, {
              onSuccess: () => toast.success("Задача продолжает выполнение"),
              onError: onError("Не удалось продолжить задачу"),
            })
          }
        >
          <Play className="size-3.5" />
          <span className="hidden sm:inline">Продолжить</span>
        </button>
      )}
      {canStop && (
        <button type="button" className={HEADER_BUTTON} onClick={() => setStopConfirmOpen(true)}>
          <Square className="size-3.5" />
          <span className="hidden sm:inline">Остановить</span>
        </button>
      )}
      {task.status === TaskStatus.FAILED && (
        <button
          type="button"
          className={HEADER_BUTTON}
          disabled={restartTask.isPending}
          onClick={() =>
            restartTask.mutate(undefined, {
              onSuccess: () => toast.success("Задача перезапускается с упавшей ноды"),
              onError: onError("Не удалось перезапустить"),
            })
          }
        >
          <RotateCcw className="size-3.5" />
          <span className="hidden sm:inline">Перезапустить с текущей ноды</span>
        </button>
      )}

      <Dialog open={stopConfirmOpen} onOpenChange={setStopConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Остановить задачу?</DialogTitle>
            <DialogDescription>
              Текущее обращение к сессии будет прервано, задача перейдёт в статус «Ошибка». Продолжить
              можно кнопкой «Перезапустить с текущей ноды».
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setStopConfirmOpen(false)}>
              Отмена
            </Button>
            <Button variant="danger" onClick={handleStop} disabled={stopTask.isPending}>
              Остановить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
