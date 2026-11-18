import { ExternalLinkField } from "@/components/tasks/ExternalLinkField";
import type { Task } from "@/lib/types";

/** Ссылки задачи: гайд и задача Jira (раздел 15.2, 15.6) — в новой вкладке; нет ссылок — ничего. */
export function TaskLinks({ task }: { task: Task }) {
  return (
    <>
      {task.guide_url && <ExternalLinkField label="Гайд" href={task.guide_url} text="Открыть гайд" />}
      {task.jira_issue_url && (
        <ExternalLinkField label="Задача в Jira" href={task.jira_issue_url} text="Открыть в Jira" />
      )}
    </>
  );
}
