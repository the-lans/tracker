import { toast } from "sonner";
import { Play } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { usePeriodicTasks, useRunPeriodicTaskNow, useUpdatePeriodicTask } from "@/hooks/useAdmin";
import { formatDateTime } from "@/lib/utils";
import { ApiError } from "@/lib/apiClient";
import { PeriodicRunStatus, PeriodicScheduleType, type PeriodicTask } from "@/lib/types";

const STATUS_TONE: Record<PeriodicRunStatus, "success" | "danger" | "info"> = {
  [PeriodicRunStatus.SUCCESS]: "success",
  [PeriodicRunStatus.FAILED]: "danger",
  [PeriodicRunStatus.RUNNING]: "info",
};

function PeriodicTaskRow({ task }: { task: PeriodicTask }) {
  const updateTask = useUpdatePeriodicTask(task.id);
  const runNow = useRunPeriodicTaskNow();

  return (
    <Card className="flex flex-wrap items-center gap-3">
      <div className="min-w-0 flex-1">
        <div className="font-bold">{task.display_name}</div>
        <div className="text-[11.5px] text-text-3">{task.description}</div>
        <div className="mt-1 font-mono text-[11px] text-text-3">
          {task.schedule_type === PeriodicScheduleType.INTERVAL
            ? `каждые ${task.interval_seconds}с`
            : task.crontab_expression}
        </div>
      </div>
      {task.last_run_status && (
        <Badge tone={STATUS_TONE[task.last_run_status]}>{task.last_run_status}</Badge>
      )}
      <div className="text-[11.5px] text-text-3">{formatDateTime(task.last_run_at)}</div>
      <Switch
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
    </Card>
  );
}

export function PeriodicTasksPanel() {
  const { data: tasks, isLoading } = usePeriodicTasks();
  return (
    <div className="flex flex-col gap-2">
      <div className="text-[12.5px] font-extrabold text-text-2">Периодические задачи</div>
      {isLoading && <div className="text-text-3">Загрузка…</div>}
      {(tasks ?? []).map((task) => (
        <PeriodicTaskRow key={task.id} task={task} />
      ))}
    </div>
  );
}
