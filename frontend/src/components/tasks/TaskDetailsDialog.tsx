import { useState } from "react";
import { Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { TitledSection } from "@/components/common/typography/TitledSection";
import { TaskArtifactList } from "@/components/tasks/TaskArtifactList";
import { TaskDescriptionBody } from "@/components/tasks/TaskDescriptionBody";
import { TaskDescriptionEditor } from "@/components/tasks/TaskDescriptionEditor";
import { TaskLinks } from "@/components/tasks/TaskLinks";
import { useTaskArtifacts } from "@/hooks/useTaskArtifacts";
import { isPreLaunch } from "@/lib/taskStatusTransitions";
import type { Task } from "@/lib/types";

/**
 * Окно поверх страницы задачи: название, описание, ссылки и артефакты крупно и
 * без остального обзора — чтобы изучить задачу внимательно (раздел 15.2). Файлы
 * только скачиваются; загрузка и удаление — в карточке «Артефакты» обзора.
 * Описание правится только здесь и только до запуска задачи (раздел 12.1).
 */
export function TaskDetailsDialog({
  task,
  open,
  onOpenChange,
}: {
  task: Task;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const {
    data: artifacts,
    isLoading,
    isError,
  } = useTaskArtifacts(task.id, false);
  const hasLinks = task.guide_url !== null || task.jira_issue_url !== null;
  const [editing, setEditing] = useState(false);
  const editable = isPreLaunch(task.status);

  function handleOpenChange(next: boolean) {
    // Недописанная правка не переживает закрытие окна.
    if (!next) setEditing(false);
    onOpenChange(next);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="max-h-[90vh] max-w-4xl space-y-5"
        onEscapeKeyDown={(event) => {
          // Escape во время правки отменяет правку, а не закрывает окно.
          if (!editing) return;
          event.preventDefault();
          setEditing(false);
        }}
      >
        <DialogHeader className="mb-0">
          <div className="font-mono text-small font-bold text-text-3">
            {task.code}
          </div>
          <DialogTitle className="break-words text-display">
            {task.title}
          </DialogTitle>
          <DialogDescription className="sr-only">
            Название, описание, ссылки и артефакты задачи {task.code}
          </DialogDescription>
        </DialogHeader>
        <TitledSection
          title="Описание"
          action={
            editable && !editing ? (
              <Button type="button" variant="ghost" size="sm" onClick={() => setEditing(true)}>
                <Pencil className="size-3" />
                Изменить
              </Button>
            ) : undefined
          }
        >
          {editing ? (
            <TaskDescriptionEditor task={task} onClose={() => setEditing(false)} />
          ) : (
            <TaskDescriptionBody task={task} />
          )}
        </TitledSection>
        <TitledSection title="Ссылки">
          {hasLinks ? (
            <TaskLinks task={task} />
          ) : (
            <p className="text-note text-text-3">Ссылок нет</p>
          )}
        </TitledSection>
        <TitledSection title="Артефакты">
          <TaskArtifactList
            task={task}
            artifacts={artifacts}
            isLoading={isLoading}
            isError={isError}
            readOnly
          />
        </TitledSection>
      </DialogContent>
    </Dialog>
  );
}
