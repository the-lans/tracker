import { toast } from "sonner";
import { Play, Timer } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { usePeriodicTasks, useRunPeriodicTaskNow, useUpdatePeriodicTask } from "@/hooks/useAdmin";
import { formatDateTime, formatInterval } from "@/lib/utils";
import { ApiError } from "@/lib/apiClient";
import { PeriodicScheduleType, type PeriodicTask } from "@/lib/types";
import { PERIODIC_RUN_STATUS_LABEL, PERIODIC_RUN_STATUS_TONE } from "@/lib/labels";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { SectionTitle } from "@/components/common/typography/SectionTitle";

function PeriodicTaskRow({ task }: { task: PeriodicTask }) {
  const updateTask = useUpdatePeriodicTask(task.id);
  const runNow = useRunPeriodicTaskNow();

  return (
    <Card className="flex flex-wrap items-center gap-x-3 gap-y-2">
      {/* basis-64: на узком экране статус и кнопки уходят под описание. */}
      <div className="min-w-0 flex-1 basis-64">
        <div className="font-bold">{task.display_name}</div>
        <div className="text-meta text-text-3">{task.description}</div>
        <div className="mt-1 text-meta text-text-3">
          {task.schedule_type === PeriodicScheduleType.INTERVAL
            ? formatInterval(task.interval_seconds ?? 0)
            : `по расписанию cron: ${task.crontab_expression}`}
        </div>
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-3">
      {task.last_run_status && (
        <Badge tone={PERIODIC_RUN_STATUS_TONE[task.last_run_status]}>
          {PERIODIC_RUN_STATUS_LABEL[task.last_run_status]}
        </Badge>
      )}
      <div className="text-meta text-text-3">{formatDateTime(task.last_run_at)}</div>
      <Switch
        aria-label={`Включить задачу ${task.display_name}`}
        checked={task.is_enabled}
        onCheckedChange={(checked) =>
          updateTask.mutate(
            { is_enabled: checked },
            {
              onError: (error) =>
                toast.error(error instanceof ApiError ? error.message : "Не удалось изменить"),
            },
          )
        }
      />
      <Button
        size="icon"
        variant="secondary"
        aria-label={`Запустить ${task.display_name} сейчас`}
        onClick={() =>
          runNow.mutate(task.id, {
            onSuccess: () => toast.success("Задача запущена вне расписания"),
            onError: (error) =>
              toast.error(error instanceof ApiError ? error.message : "Не удалось запустить"),
          })
        }
      >
        <Play className="size-3.5" />
      </Button>
      </div>
    </Card>
  );
}

export function PeriodicTasksPanel() {
  const { data: tasks, isLoading } = usePeriodicTasks();
  return (
    <div className="flex flex-col gap-2">
      <SectionTitle>Периодические задачи</SectionTitle>
      {isLoading && <LoadingState />}
      {!isLoading && (tasks ?? []).length === 0 && (
        <EmptyState
          icon={Timer}
          title="Периодические задачи не заполнены"
          hint="Их создаёт скрипт первичного заполнения scripts/seed_periodic_tasks.py — администратор сервера запускает его после первого входа в систему."
        />
      )}
      {(tasks ?? []).map((task) => (
        <PeriodicTaskRow key={task.id} task={task} />
      ))}
    </div>
  );
}
