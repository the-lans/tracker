import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ExternalLinkField } from "@/components/tasks/ExternalLinkField";
import { TaskDescriptionHtml } from "@/components/tasks/TaskDescriptionHtml";
import { useRefreshJiraDescription } from "@/hooks/useTasks";
import { errorMessage } from "@/lib/errors";
import type { Task } from "@/lib/types";

/**
 * Описание задачи и ссылки на гайд и задачу Jira (раздел 15.2, 15.6). Описание,
 * импортированное из Jira, показывается отрисованным (HTML Jira); без него —
 * обычным текстом.
 */
export function TaskDescriptionCard({ task }: { task: Task }) {
  const refresh = useRefreshJiraDescription(task.id);
  return (
    <Card>
      <div className="mb-1 flex items-center justify-between gap-2 text-meta font-bold text-text-3">
        Описание
        {task.jira_issue_url && (
          <Button
            variant="ghost"
            size="sm"
            disabled={refresh.isPending}
            onClick={() =>
              refresh.mutate(undefined, {
                onSuccess: () => toast.success("Описание обновлено из Jira"),
                onError: (error) =>
                  toast.error(errorMessage(error, "Не удалось обновить описание из Jira")),
              })
            }
          >
            <RefreshCw className="size-3" />
            Обновить из Jira
          </Button>
        )}
      </div>
      {task.description_html ? (
        <TaskDescriptionHtml
          taskId={task.id}
          html={task.description_html}
          jiraUrl={task.jira_issue_url}
        />
      ) : (
        <div className="whitespace-pre-wrap text-body leading-relaxed text-text-2">
          {task.description}
        </div>
      )}
      {task.guide_url && (
        <ExternalLinkField
          label="Гайд"
          href={task.guide_url}
          text="Открыть гайд"
        />
      )}
      {task.jira_issue_url && (
        <ExternalLinkField
          label="Задача в Jira"
          href={task.jira_issue_url}
          text="Открыть в Jira"
        />
      )}
    </Card>
  );
}
