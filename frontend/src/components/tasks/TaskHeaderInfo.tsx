import { TaskLlmAccountBadge } from "@/components/tasks/TaskLlmAccountBadge";
import { cn } from "@/lib/utils";
import type { Task } from "@/lib/types";

/**
 * Строка аккаунта задачи и под ней пояснение шапки (например, «Просмотр в
 * claude.ai/code недоступен», раздел 6.3); ``note`` пустой — только аккаунт.
 */
export function TaskHeaderInfo({
  task,
  note,
  className,
  truncateNote = false,
}: {
  task: Task;
  note: string | null;
  className?: string;
  truncateNote?: boolean;
}) {
  return (
    <div className={cn("empty:hidden", className)}>
      <TaskLlmAccountBadge task={task} />
      {note && (
        <p
          className={cn("text-caption text-text-3", truncateNote && "truncate")}
        >
          {note}
        </p>
      )}
    </div>
  );
}
