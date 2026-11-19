import { Card } from "@/components/ui/card";
import { RefreshJiraDescriptionButton } from "@/components/tasks/RefreshJiraDescriptionButton";
import { TaskLinks } from "@/components/tasks/TaskLinks";
import { TaskDescriptionBody } from "@/components/tasks/TaskDescriptionBody";
import type { Task } from "@/lib/types";

/**
 * Описание задачи и ссылки на гайд и задачу Jira (раздел 15.2, 15.6). Описание,
 * импортированное из Jira, показывается отрисованным (HTML Jira); без него —
 * обычным текстом.
 */
export function TaskDescriptionCard({ task }: { task: Task }) {
  return (
    <Card>
      <div className="mb-1 flex items-center justify-between gap-2 text-meta font-bold text-text-3">
        Описание
        {task.jira_issue_url && (
          <RefreshJiraDescriptionButton taskId={task.id} />
        )}
      </div>
      <TaskDescriptionBody task={task} />
      <TaskLinks task={task} />
    </Card>
  );
}
