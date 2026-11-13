import { Link } from "react-router-dom";
import { OwnerLabel } from "@/components/common/avatar/OwnerLabel";
import { TaskStatusBadge } from "@/components/tasks/TaskStatusBadge";
import type { ArchivedTask } from "@/lib/archive.types";
import { TaskStatus } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { WRAP_ROW } from "@/styles/classes";

/**
 * Раздел 15.1: строка архива — код, название, итоговый статус, категория и
 * даты; на узком экране переносится на вторую строку.
 */
export function ArchivedTaskRow({ task }: { task: ArchivedTask }) {
  return (
    <li>
      <Link
        to={`/tasks/${task.id}`}
        aria-label={`${task.code} · ${task.title}`}
        className="flex min-w-0 flex-col gap-1.5 rounded-lg border border-border bg-surface p-3 transition-colors hover:border-accent-border sm:flex-row sm:items-center sm:gap-4"
      >
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="shrink-0 font-mono text-small font-bold text-text-2">{task.code}</span>
            <span className="min-w-0 truncate text-body font-semibold text-text" title={task.title}>
              {task.title}
            </span>
          </div>
          <OwnerLabel ownerId={task.created_by} />
        </div>
        <div className={`${WRAP_ROW} text-caption tabular-nums text-text-3 sm:shrink-0 sm:justify-end`}>
          <TaskStatusBadge status={task.archived_from_status ?? TaskStatus.ARCHIVED} />
          {task.category_name && (
            <span className="max-w-40 truncate" title={task.category_name}>
              {task.category_name}
            </span>
          )}
          <span>
            Завершена <time dateTime={task.finished_at ?? undefined}>{formatDateTime(task.finished_at)}</time>
          </span>
          {task.repo_cleaned_at && <span>Репозитории очищены</span>}
        </div>
      </Link>
    </li>
  );
}
