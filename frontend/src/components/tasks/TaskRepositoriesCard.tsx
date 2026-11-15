import { useState } from "react";
import { GitBranch, Plus } from "lucide-react";
import { Card, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useRepositories } from "@/hooks/useRepositories";
import { useRemoveTaskRepository, useTaskRepositories } from "@/hooks/useTasks";
import { MergeStatus, type Task, type TaskRepository } from "@/lib/types";
import { REPOSITORY_ROLE_LABEL } from "@/lib/labels";
import { toastError } from "@/lib/errors";
import { isReadOnly, isTaskRepositoryRemovable } from "@/lib/taskStatusTransitions";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { AddTaskRepositoriesDialog } from "@/components/tasks/AddTaskRepositoriesDialog";

const MERGE_STATUS_LABELS: Record<MergeStatus, string> = {
  [MergeStatus.NOT_PUSHED]: "не запушено",
  [MergeStatus.PUSHED]: "запушено",
  [MergeStatus.MERGED]: "смерджено",
  [MergeStatus.CONFLICT]: "конфликт",
};

function TaskRepositoryRow({
  task,
  taskRepository,
  name,
}: {
  task: Task;
  taskRepository: TaskRepository;
  name: string;
}) {
  const removeRepository = useRemoveTaskRepository(task.id);

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-border py-2 first:border-t-0">
      <div className="w-full min-w-0 break-words text-note font-bold [overflow-wrap:anywhere]" title={name}>
        {name}
      </div>
      {taskRepository.cloned_at === null && <Badge>ещё не склонирован</Badge>}
      <Badge>{REPOSITORY_ROLE_LABEL[taskRepository.role]}</Badge>
      {isTaskRepositoryRemovable(task, taskRepository) && (
        <ConfirmDeleteButton
          kind="репозиторий из задачи"
          name={name}
          pending={removeRepository.isPending}
          onConfirm={() =>
            removeRepository.mutate(taskRepository.id, {
              onError: toastError("Не удалось убрать репозиторий"),
            })
          }
        />
      )}
      <div className="flex w-full min-w-0 flex-wrap items-center gap-1.5 font-mono text-meta text-text-3">
        <GitBranch className="size-3 shrink-0" />
        <span className="min-w-0 [overflow-wrap:anywhere]">
          {taskRepository.branch_name} ← {taskRepository.base_branch}
        </span>
        <span className="ml-auto font-sans">{MERGE_STATUS_LABELS[taskRepository.merge_status]}</span>
      </div>
    </div>
  );
}

export function TaskRepositoriesCard({ task }: { task: Task }) {
  const { data: taskRepositories, isLoading } = useTaskRepositories(task.id);
  const { data: repositories } = useRepositories();
  const [addOpen, setAddOpen] = useState(false);
  const namesById = new Map((repositories ?? []).map((repository) => [repository.id, repository.name]));
  const canAdd = !isReadOnly(task.status);

  return (
    <Card>
      <CardTitle>
        <span>Репозитории</span>
        {canAdd ? (
          <Button size="sm" variant="secondary" onClick={() => setAddOpen(true)}>
            <Plus className="size-3.5" /> Добавить
          </Button>
        ) : (
          taskRepositories && <span>{taskRepositories.length}</span>
        )}
      </CardTitle>
      {isLoading ? (
        <LoadingState />
      ) : taskRepositories?.length ? (
        <div className="flex flex-col">
          {taskRepositories.map((taskRepository) => (
            <TaskRepositoryRow
              key={taskRepository.id}
              task={task}
              taskRepository={taskRepository}
              name={namesById.get(taskRepository.repository_id) ?? taskRepository.repository_id}
            />
          ))}
        </div>
      ) : (
        <EmptyState
          compact
          title="Репозитории не привязаны"
          hint={
            canAdd
              ? "Добавьте репозитории кнопкой «Добавить» — и сейчас, и когда по ходу задачи станет ясно, какие нужны."
              : "Задача завершена: чтобы работать с другим набором репозиториев, верните её в статус до запуска или продублируйте."
          }
        />
      )}
      {canAdd && (
        <AddTaskRepositoriesDialog
          taskId={task.id}
          attachedIds={new Set((taskRepositories ?? []).map((item) => item.repository_id))}
          open={addOpen}
          onOpenChange={setAddOpen}
        />
      )}
    </Card>
  );
}
