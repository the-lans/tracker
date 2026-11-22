import { useState } from "react";
import { Maximize2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { RefreshJiraDescriptionButton } from "@/components/tasks/RefreshJiraDescriptionButton";
import { Button } from "@/components/ui/button";
import { ClampedContent } from "@/components/common/typography/ClampedContent";
import { TaskDetailsDialog } from "@/components/tasks/TaskDetailsDialog";
import { TaskLinks } from "@/components/tasks/TaskLinks";
import { TaskDescriptionBody } from "@/components/tasks/TaskDescriptionBody";
import type { Task } from "@/lib/types";

/**
 * Описание задачи и ссылки на гайд и задачу Jira (раздел 15.2, 15.6). Описание,
 * импортированное из Jira, показывается отрисованным (HTML Jira); без него —
 * обычным текстом. Длинное описание в карточке обрезается, целиком оно — в
 * окне «В отдельном окне».
 */
export function TaskDescriptionCard({ task }: { task: Task }) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  return (
    <Card>
      <div className="mb-1 flex items-center justify-between gap-2 text-meta font-bold text-text-3">
        Описание
        {task.jira_issue_url && (
          <RefreshJiraDescriptionButton taskId={task.id} />
        )}
      </div>
      <ClampedContent
        renderMore={() => (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="touch-hit mt-1 h-7 min-h-0! px-2"
            onClick={() => setDetailsOpen(true)}
          >
            <Maximize2 className="size-3" />
            Открыть полностью
          </Button>
        )}
      >
        <TaskDescriptionBody task={task} />
      </ClampedContent>
      <TaskLinks task={task} />
      <TaskDetailsDialog task={task} open={detailsOpen} onOpenChange={setDetailsOpen} />
    </Card>
  );
}
