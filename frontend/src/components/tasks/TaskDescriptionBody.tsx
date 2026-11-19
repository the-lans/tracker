import { TaskDescriptionHtml } from "@/components/tasks/TaskDescriptionHtml";
import type { Task } from "@/lib/types";

/**
 * Текст описания задачи (раздел 15.2, 15.6): импортированное из Jira — отрисованным
 * (HTML Jira), иначе обычным текстом с переносами строк.
 */
export function TaskDescriptionBody({ task }: { task: Task }) {
  if (task.description_html) {
    return (
      <TaskDescriptionHtml
        taskId={task.id}
        html={task.description_html}
        jiraUrl={task.jira_issue_url}
      />
    );
  }
  return (
    <div className="whitespace-pre-wrap text-body leading-relaxed text-text-2">
      {task.description}
    </div>
  );
}
