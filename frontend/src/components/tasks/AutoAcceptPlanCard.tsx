import { Card } from "@/components/ui/card";
import { AutoAcceptPlanField } from "@/components/tasks/AutoAcceptPlanField";
import { isReadOnly } from "@/lib/taskStatusTransitions";
import type { Task, TaskUpdateRequest } from "@/lib/types";

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
      <AutoAcceptPlanField
        checked={task.auto_accept_plan}
        disabled={isReadOnly(task.status) || pending}
        onCheckedChange={(checked) => onUpdate({ auto_accept_plan: checked })}
      />
    </Card>
  );
}
