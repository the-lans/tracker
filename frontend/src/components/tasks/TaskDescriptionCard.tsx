import { Card } from "@/components/ui/card";
import { ExternalLinkField } from "@/components/tasks/ExternalLinkField";
import type { Task } from "@/lib/types";

/** Описание задачи и ссылки на гайд и задачу Jira (раздел 15.2, 15.6). */
export function TaskDescriptionCard({ task }: { task: Task }) {
  return (
    <Card>
      <div className="mb-1 text-meta font-bold text-text-3">Описание</div>
      <div className="text-body leading-relaxed text-text-2">{task.description}</div>
      {task.guide_url && (
        <ExternalLinkField label="Гайд" href={task.guide_url} text="Открыть гайд" />
      )}
      {task.jira_issue_url && (
        <ExternalLinkField label="Задача в Jira" href={task.jira_issue_url} text="Открыть в Jira" />
      )}
    </Card>
  );
}
