import { Ban, Pause, Play, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { HEADER_BUTTON } from "@/styles/classes";
import { MANUAL_REQUEST_STATUSES } from "@/components/tasks/taskStatusMeta";
import { TaskStopButton } from "@/components/tasks/TaskStopButton";
import { TaskLifecycleActions } from "@/components/tasks/TaskLifecycleActions";
import {
  useCancelQueuedTask,
  usePauseTask,
  useRestartTask,
  useStartTask,
  useResumeTask,
  useLlmLimit,
} from "@/hooks/useTasks";
import { toastError } from "@/lib/errors";
import { launchWaitHint } from "@/lib/llmAccounts";
import { cn } from "@/lib/utils";
import { TaskStatus, type Task } from "@/lib/types";
import { ButtonLabel } from "@/components/common/actions/ButtonLabel";
import { isPreLaunch } from "@/lib/taskStatusTransitions";

/** Раздел 19.7: из ожидания лимита на паузу встаёт только выполнявшаяся задача. */
const PAUSABLE_LIMIT_WAIT_FROM: (TaskStatus | null | undefined)[] = [
  TaskStatus.IN_PROGRESS,
  TaskStatus.REBASE_CONFLICT,
];

/** Раздел 14.2: действия пользователя, доступные в текущем статусе задачи. */
export function TaskControlButtons({ task }: { task: Task }) {
  const pauseTask = usePauseTask(task.id);
  const resumeTask = useResumeTask(task.id);
  const cancelTask = useCancelQueuedTask(task.id);
  const restartTask = useRestartTask(task.id);
  const startTask = useStartTask(task.id);
  const limitWait = task.status === TaskStatus.AWAITING_LIMIT;
  const canPause =
    task.status === TaskStatus.IN_PROGRESS ||
    (limitWait && PAUSABLE_LIMIT_WAIT_FROM.includes(task.limit_wait_from_status));
  const canStop = task.status === TaskStatus.IN_PROGRESS || task.status === TaskStatus.PAUSED || limitWait;
  // Запрос чата можно остановить везде, где чат принимает запросы, включая «Уточняется».
  const canStopRequests =
    MANUAL_REQUEST_STATUSES.includes(task.status) || task.status === TaskStatus.REFINING;
  const preLaunch = isPreLaunch(task.status);
  const { data: llmLimit } = useLlmLimit(task.created_by, preLaunch);
  const launchWaitUntil = preLaunch ? llmLimit?.wait_until : null;

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {/* Раздел 14.2: запуск новой задачи — прямо со страницы, где её настраивают. */}
      {preLaunch && (
        <button
          type="button"
          className={cn(HEADER_BUTTON, task.pipeline_id && "border-accent bg-accent text-on-accent")}
          aria-label="Запустить задачу"
          title={task.pipeline_id ? "Запустить задачу" : "Сначала выберите пайплайн на вкладке «Обзор»"}
          disabled={!task.pipeline_id || task.chat_active || startTask.isPending}
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
      {canPause && (
        <button
          type="button"
          className={HEADER_BUTTON}
          aria-label="Приостановить"
          title="Приостановить"
          disabled={pauseTask.isPending}
          onClick={() =>
            pauseTask.mutate(undefined, {
              onSuccess: () =>
                toast.success(limitWait ? "После сброса лимита задача встанет на паузу" : "Пауза наступит после текущей ноды"),
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
      {(canStop || canStopRequests) && <TaskStopButton taskId={task.id} canStopTask={canStop} />}
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
      {launchWaitUntil && (
        <p className="basis-full text-right text-caption text-warning-text">
          {launchWaitHint(launchWaitUntil)}
        </p>
      )}
    </div>
  );
}
