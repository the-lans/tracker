import { TaskLlmAccountBadge } from "@/components/tasks/TaskLlmAccountBadge";
import { cn } from "@/lib/utils";
import type { Task } from "@/lib/types";

/** Строка аккаунта задачи в шапке (раздел 15.2). */
export function TaskHeaderInfo({ task, className }: { task: Task; className?: string }) {
  return (
    <div className={cn("empty:hidden", className)}>
      <TaskLlmAccountBadge task={task} />
    </div>
  );
}
