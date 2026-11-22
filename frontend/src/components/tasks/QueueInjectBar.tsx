import { Clock, CornerDownRight, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useInjectManualRequest } from "@/hooks/useTasks";
import { errorMessage } from "@/lib/errors";
import type { QueueSummary } from "@/lib/manualQueue";
import { TaskStatus, type InjectionResult } from "@/lib/types";

/** Причины отказа воркера во влитии (раздел 7.3) — подписи для тоста. */
const INJECTION_REFUSALS: Record<string, string> = {
  no_turn: "Сейчас нет хода модели — влить нечего",
  awaiting_decision: "Агент ждёт вашего решения — влить нельзя",
  nothing_to_inject: "В очереди только команды — их нельзя влить",
  nothing_to_cancel: "Нет влитого промта, который можно вернуть",
  too_late: "Агент уже взял промт — отменить нельзя",
  failed: "Не удалось влить промт",
};
const NOT_RUNNING_HINT = "Влить можно, пока агент работает над задачей";
const INJECT_HINT = "Влить в текущий ход: ближайший промт уйдёт агенту сейчас";
const CANCEL_HINT = "Вернуть последний влитый промт в очередь, пока агент его не взял";
const BUTTON_CLASS = "h-6 min-h-0! min-w-7! gap-1 px-1.5 text-meta";

/**
 * Строка «В очереди: N» над полем ввода и рядом с ней компактные кнопки «Влить в
 * текущий ход» и «Отменить» (на узком экране — только значки), под ней — «Влито: K».
 */
export function QueueInjectBar({
  taskId,
  taskStatus,
  summary,
}: {
  taskId: string;
  taskStatus: TaskStatus;
  summary: QueueSummary;
}) {
  const inject = useInjectManualRequest(taskId, "inject");
  const cancelInjected = useInjectManualRequest(taskId, "inject/cancel");
  const running = taskStatus === TaskStatus.IN_PROGRESS;
  const injectHint = !running
    ? NOT_RUNNING_HINT
    : summary.injectable === 0
      ? INJECTION_REFUSALS.nothing_to_inject
      : INJECT_HINT;

  function runInjection(mutation: typeof inject, success: string) {
    mutation.mutate(undefined, {
      onSuccess: (result: InjectionResult) => {
        if (result.ok) toast.success(success);
        else toast.error(INJECTION_REFUSALS[result.reason ?? "failed"] ?? result.message ?? INJECTION_REFUSALS.failed);
      },
      onError: (error) => toast.error(errorMessage(error, INJECTION_REFUSALS.failed)),
    });
  }

  return (
    <div className="mb-0.5 flex flex-wrap items-center gap-x-2 leading-tight">
      <span className="flex items-center gap-1.5 text-meta font-bold text-info-text">
        <Clock className="size-3" />В очереди: {summary.queued}
      </span>
      <span className="ml-auto flex items-center gap-1">
        {summary.injected > 0 && (
          <Button
            size="sm"
            variant="secondary"
            className={BUTTON_CLASS}
            aria-label="Отменить"
            title={CANCEL_HINT}
            disabled={cancelInjected.isPending}
            onClick={() => runInjection(cancelInjected, "Промт возвращён в очередь")}
          >
            <Undo2 className="size-3.5" />
            <span className="hidden sm:inline">Отменить</span>
          </Button>
        )}
        {summary.queued > 0 && (
          <Button
            size="sm"
            variant="primary"
            className={BUTTON_CLASS}
            aria-label="Влить в текущий ход"
            title={injectHint}
            disabled={!running || summary.injectable === 0 || inject.isPending}
            onClick={() => runInjection(inject, "Промт влит в текущий ход")}
          >
            <CornerDownRight className="size-3.5" />
            <span className="hidden sm:inline">Влить в текущий ход</span>
          </Button>
        )}
      </span>
      {summary.injected > 0 && (
        <span className="basis-full text-meta text-text-3">Влито: {summary.injected} — дойдёт после текущего шага</span>
      )}
    </div>
  );
}
