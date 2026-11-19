import { useEffect, useState } from "react";
import { Square } from "lucide-react";
import { toast } from "sonner";
import { ButtonLabel } from "@/components/common/actions/ButtonLabel";
import { ConfirmDialog } from "@/components/common/dialogs/ConfirmDialog";
import {
  useManualQueue,
  useStopManualRequest,
  useStopTask,
} from "@/hooks/useTasks";
import { errorMessage, toastError } from "@/lib/errors";
import { nextStoppableRequest, stopRequestLabel } from "@/lib/manualRequests";
import { cn } from "@/lib/utils";
import { HEADER_BUTTON } from "@/styles/classes";

const STOP_DESCRIPTION =
  "Текущее выполнение будет прервано, оставшиеся ноды и автоматический пуш не выполнятся. Задача перейдёт в статус «Готово».";

/** Пауза после остановки запроса: двойной щелчок не должен сразу завершить задачу. */
export const STOP_TASK_ARMING_MS = 1500;

const DANGER_CLASS =
  "border-danger/50 bg-danger-tint text-danger-text hover:border-danger hover:bg-danger-tint hover:text-danger-text";

/**
 * «Остановить» в шапке задачи (раздел 14.2). Пока в чате есть запрос — свободный промт
 * или команда, — каждое нажатие останавливает один из них (сначала выполняющийся, потом
 * ожидающие), кнопка обычная. Когда останавливать больше нечего, она красная и
 * завершает всю задачу — после подтверждения и паузы в {@link STOP_TASK_ARMING_MS}.
 * Где задачу завершить нельзя (``canStopTask`` = false), кнопка есть только пока есть запрос.
 */
export function TaskStopButton({
  taskId,
  canStopTask,
}: {
  taskId: string;
  /** Задачу можно завершить: в статусе без этого (чат «Уточняется», ответ агента) кнопка только для запросов. */
  canStopTask: boolean;
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [stoppedIds, setStoppedIds] = useState<ReadonlySet<string>>(new Set());
  const [arming, setArming] = useState(false);
  const stopTask = useStopTask(taskId);
  const stopRequest = useStopManualRequest(taskId);
  const { data: queue } = useManualQueue(taskId);
  // Остановленный запрос остаётся в списке до очередного опроса — второй раз его не трогаем.
  const request = nextStoppableRequest(
    (queue ?? []).filter((item) => !stoppedIds.has(item.id)),
  );

  useEffect(() => {
    if (!arming) return;
    const timer = setTimeout(() => setArming(false), STOP_TASK_ARMING_MS);
    return () => clearTimeout(timer);
  }, [arming]);

  function handleStopRequest(target: string) {
    stopRequest.mutate(target, {
      onSuccess: () => {
        setStoppedIds((ids) => new Set(ids).add(target));
        setArming(true);
      },
      onError: (error) =>
        toast.error(errorMessage(error, "Не удалось остановить запрос")),
    });
  }

  function handleStopTask() {
    stopTask.mutate(undefined, {
      onSuccess: () => {
        setConfirmOpen(false);
        toast.success("Задача останавливается");
      },
      onError: toastError("Не удалось остановить задачу"),
    });
  }

  if (!request && !canStopTask) return null;

  const label = request ? stopRequestLabel(request) : "Остановить";
  const title = request
    ? `${label}: задача продолжит работу. Следующее нажатие остановит следующий запрос, а затем всю задачу`
    : "Остановить задачу целиком";

  return (
    <>
      <button
        type="button"
        className={cn(HEADER_BUTTON, !request && DANGER_CLASS)}
        aria-label={label}
        title={title}
        disabled={stopRequest.isPending || (!request && arming)}
        onClick={() =>
          request ? handleStopRequest(request.id) : setConfirmOpen(true)
        }
      >
        <Square className="size-3.5" />
        <ButtonLabel>{label}</ButtonLabel>
      </button>
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Остановить задачу?"
        description={STOP_DESCRIPTION}
        confirmLabel="Остановить"
        danger
        pending={stopTask.isPending}
        onConfirm={handleStopTask}
      />
    </>
  );
}
