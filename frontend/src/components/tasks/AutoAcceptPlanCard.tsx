import { Card } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { TaskStatus, type Task, type TaskUpdateRequest } from "@/lib/types";

/** Раздел 9.4: план принимается без остановки на ревью. */
export function AutoAcceptPlanCard({
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
          <div className="text-body font-bold">Принять план автоматически</div>
          <div className="mt-0.5 text-meta text-text-3">Без остановки на ревью плана</div>
        </div>
        <Switch
          checked={task.auto_accept_plan}
          disabled={task.status === TaskStatus.DONE || pending}
          onCheckedChange={(checked) => onUpdate({ auto_accept_plan: checked })}
        />
      </div>
    </Card>
  );
}
