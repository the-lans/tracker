import { useState } from "react";
import { Check, Pencil, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useUpdatePeriodicTask } from "@/hooks/useAdmin";
import { toastError } from "@/lib/errors";
import { formatInterval } from "@/lib/utils";
import { PeriodicScheduleType, type PeriodicTask, type PeriodicTaskUpdateRequest } from "@/lib/types";

function scheduleText(task: PeriodicTask): string {
  return task.schedule_type === PeriodicScheduleType.INTERVAL
    ? formatInterval(task.interval_seconds ?? 0)
    : `по расписанию cron: ${task.crontab_expression}`;
}

function currentValue(task: PeriodicTask): string {
  return task.schedule_type === PeriodicScheduleType.INTERVAL
    ? String(task.interval_seconds ?? "")
    : (task.crontab_expression ?? "");
}

/** Возвращает тело запроса или null, если черновик заведомо неверен. */
function toUpdate(task: PeriodicTask, draft: string): PeriodicTaskUpdateRequest | null {
  const value = draft.trim();
  if (task.schedule_type === PeriodicScheduleType.CRONTAB) {
    return value ? { crontab_expression: value } : null;
  }
  const seconds = Number(value);
  return Number.isInteger(seconds) && seconds > 0 ? { interval_seconds: seconds } : null;
}

/**
 * Раздел 15.5, 16.1: расписание периодической задачи меняется из админки без
 * деплоя. Тип расписания задан задачей — правится только его значение.
 */
export function PeriodicScheduleEditor({ task }: { task: PeriodicTask }) {
  const updateTask = useUpdatePeriodicTask(task.id);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const isInterval = task.schedule_type === PeriodicScheduleType.INTERVAL;
  const body = toUpdate(task, draft);

  function handleSave() {
    if (!body) return;
    updateTask.mutate(body, {
      onSuccess: () => setEditing(false),
      onError: toastError("Не удалось сохранить расписание"),
    });
  }

  if (editing) {
    return (
      <div className="flex flex-wrap items-center gap-1">
        <Input
          aria-label={isInterval ? "Интервал, секунд" : "Расписание cron"}
          className="h-8 max-w-48 font-mono"
          inputMode={isInterval ? "numeric" : undefined}
          placeholder={isInterval ? "300" : "0 3 * * *"}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <Button
          size="icon"
          variant="ghost"
          aria-label="Сохранить расписание"
          disabled={!body || updateTask.isPending}
          onClick={handleSave}
        >
          <Check className="size-4" />
        </Button>
        <Button size="icon" variant="ghost" aria-label="Отмена" onClick={() => setEditing(false)}>
          <X className="size-4" />
        </Button>
        <span className="basis-full text-caption text-text-3">
          {isInterval
            ? "Интервал в секундах"
            : "5 полей: минута час день_месяца месяц день_недели"}
        </span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1 text-meta text-text-3">
      <span>{scheduleText(task)}</span>
      <button
        type="button"
        className="touch-target flex shrink-0 items-center justify-center hover:text-accent"
        aria-label={`Изменить расписание ${task.display_name}`}
        title="Изменить расписание"
        onClick={() => {
          setDraft(currentValue(task));
          setEditing(true);
        }}
      >
        <Pencil className="size-3.5" />
      </button>
    </div>
  );
}
