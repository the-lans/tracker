import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSystemSettings } from "@/hooks/useAdmin";
import { isQueued } from "@/lib/taskStatusTransitions";
import { formatDateTime } from "@/lib/utils";
import { TaskStatus, type Task, type TaskUpdateRequest } from "@/lib/types";
import {
  MAX_QUEUE_PRIORITY,
  MIN_QUEUE_PRIORITY,
  QUEUE_PRIORITY_HINT,
  QUEUE_PRIORITY_RANGE_HINT,
  parseQueuePriority,
} from "@/lib/queuePriority";

/** «ЧЧ:ММ:СС» настроек → «ЧЧ:ММ». */
function clockTime(value: string): string {
  return value.slice(0, 5);
}

/**
 * Раздел 14.4: приоритет в очереди автора и галочка «Занимать слот» —
 * меняются в любом статусе; у задачи в очереди — её место и время постановки.
 */
export function TaskQueueCard({
  task,
  pending,
  onUpdate,
}: {
  task: Task;
  pending: boolean;
  onUpdate: (body: TaskUpdateRequest) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const { data: settings } = useSystemSettings();
  const shownPriority = draft ?? String(task.queue_priority);
  const parsed = parseQueuePriority(shownPriority);

  function savePriority() {
    if (draft === null) return;
    setDraft(null);
    if (parsed !== null && parsed !== task.queue_priority) onUpdate({ queue_priority: parsed });
  }

  return (
    <Card>
      <div className="text-body font-bold">Очередь</div>
      <div className="mt-2 flex items-center gap-3">
        <Label htmlFor={`queue-priority-${task.id}`} className="text-note text-text-2">
          Приоритет
        </Label>
        <Input
          id={`queue-priority-${task.id}`}
          type="number"
          inputMode="numeric"
          min={MIN_QUEUE_PRIORITY}
          max={MAX_QUEUE_PRIORITY}
          className="h-9 w-28"
          value={shownPriority}
          disabled={pending}
          aria-invalid={parsed === null}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={savePriority}
          onKeyDown={(event) => {
            if (event.key === "Enter") savePriority();
            if (event.key === "Escape") setDraft(null);
          }}
        />
      </div>
      <div className="mt-1 text-meta text-text-3">
        {parsed === null ? QUEUE_PRIORITY_RANGE_HINT : QUEUE_PRIORITY_HINT}
      </div>

      <div className="mt-3 flex items-start gap-3">
        <Checkbox
          id={`occupies-slot-${task.id}`}
          className="mt-0.5"
          checked={task.occupies_slot}
          disabled={pending}
          onCheckedChange={(checked) => onUpdate({ occupies_slot: checked === true })}
        />
        <div>
          <Label htmlFor={`occupies-slot-${task.id}`} className="text-note font-bold">
            Занимать слот параллельного запуска задач
          </Label>
          <div className="mt-0.5 text-meta text-text-3">
            Для ручного запуска и чата в «Уточняется». Задача из очереди слот занимает всегда.
          </div>
        </div>
      </div>

      {isQueued(task.status) && (
        <div className="mt-3 border-t border-border pt-2.5 text-meta text-text-2">
          {task.queue_position !== null && <div>№{task.queue_position} в очереди</div>}
          {task.ready_at && <div className="text-text-3">В очереди с {formatDateTime(task.ready_at)}</div>}
          {task.status === TaskStatus.NIGHT_WORKER && settings && (
            <div className="text-text-3">
              Запустится в ночном окне {clockTime(settings.night_window_start)}–
              {clockTime(settings.night_window_end)} МСК
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
