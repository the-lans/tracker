import { Badge } from "@/components/ui/badge";
import { TASK_STATUS_META } from "@/components/tasks/taskStatusMeta";
import type { TaskStatus } from "@/lib/types";

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  const meta = TASK_STATUS_META[status];
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}
