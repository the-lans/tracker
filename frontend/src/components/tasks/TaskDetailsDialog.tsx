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
import { TaskLinks } from "@/components/tasks/TaskLinks";
import { useTaskArtifacts } from "@/hooks/useTaskArtifacts";
import type { Task } from "@/lib/types";

/**
 * Окно поверх страницы задачи: название, описание, ссылки и артефакты крупно и
 * без остального обзора — чтобы изучить задачу внимательно (раздел 15.2). Файлы
 * только скачиваются; загрузка и удаление — в карточке «Артефакты» обзора.
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
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-4xl space-y-5">
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
        <TitledSection title="Описание">
          <TaskDescriptionBody task={task} />
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
