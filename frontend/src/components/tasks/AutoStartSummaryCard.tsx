import { Card } from "@/components/ui/card";
import { formatDateTime } from "@/lib/utils";
import type { Task } from "@/lib/types";

/** Автозапуск после старта уже не настраивается — одна строка вместо формы. */
export function AutoStartSummaryCard({ task }: { task: Task }) {
  return (
    <Card className="flex items-center justify-between gap-3 py-3">
      <div className="text-body font-bold">Автозапуск</div>
      <div className="text-small text-text-3">
        {task.auto_start_enabled && task.scheduled_start_at
          ? `был запланирован на ${formatDateTime(task.scheduled_start_at)}`
          : "не использовался"}
      </div>
    </Card>
  );
}
