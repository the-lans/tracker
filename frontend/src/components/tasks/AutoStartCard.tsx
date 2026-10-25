import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { formatDateTime } from "@/lib/utils";
import type { Task, TaskUpdateRequest } from "@/lib/types";

/** ISO-время ↔ значение `<input type="datetime-local">` в локальной зоне. */
function toLocalInputValue(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

/** Раздел 12.1: автозапуск задачи в `new` — переключатель и дата старта. */
export function AutoStartCard({
  task,
  pending,
  onUpdate,
}: {
  task: Task;
  pending: boolean;
  onUpdate: (body: TaskUpdateRequest) => void;
}) {
  return (
    <Card>
      <div className="flex items-center justify-between py-1">
        <div>
          <div className="text-body font-bold">Автозапуск</div>
          <div className="mt-0.5 text-meta text-text-3">
            {task.scheduled_start_at
              ? formatDateTime(task.scheduled_start_at)
              : "Дата и время старта"}
          </div>
        </div>
        <Switch
          checked={task.auto_start_enabled}
          disabled={pending}
          onCheckedChange={(checked) => onUpdate({ auto_start_enabled: checked })}
        />
      </div>
      {/* Раздел 12.1: пока переключатель выключен, поле даты неактивно. */}
      <Input
        type="datetime-local"
        aria-label="Дата и время автозапуска"
        className="mt-2"
        value={toLocalInputValue(task.scheduled_start_at)}
        disabled={!task.auto_start_enabled || pending}
        onChange={(event) =>
          onUpdate({
            scheduled_start_at: event.target.value
              ? new Date(event.target.value).toISOString()
              : null,
          })
        }
      />
    </Card>
  );
}
