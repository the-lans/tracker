import { GitBranch } from "lucide-react";
import { Card, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useRepositories } from "@/hooks/useRepositories";
import { useTaskRepositories } from "@/hooks/useTasks";
import { MergeStatus } from "@/lib/types";
import { REPOSITORY_ROLE_LABEL } from "@/lib/labels";
import { EmptyState } from "@/components/common/feedback/EmptyState";

const MERGE_STATUS_LABELS: Record<MergeStatus, string> = {
  [MergeStatus.NOT_PUSHED]: "не запушено",
  [MergeStatus.PUSHED]: "запушено",
  [MergeStatus.MERGED]: "смерджено",
  [MergeStatus.CONFLICT]: "конфликт",
};

export function TaskRepositoriesCard({ taskId }: { taskId: string }) {
  const { data: taskRepositories } = useTaskRepositories(taskId);
  const { data: repositories } = useRepositories();
  const namesById = new Map((repositories ?? []).map((repository) => [repository.id, repository.name]));

  return (
    <Card>
      <CardTitle>
        <span>Репозитории</span>
        {taskRepositories && <span>{taskRepositories.length}</span>}
      </CardTitle>
      {taskRepositories?.length ? (
        <div className="flex flex-col">
          {taskRepositories.map((taskRepository) => (
            <div
              key={taskRepository.id}
              className="flex flex-wrap items-center gap-2 border-t border-border py-2 first:border-t-0"
            >
              <div
                className="min-w-0 flex-1 truncate text-note font-bold"
                title={namesById.get(taskRepository.repository_id) ?? taskRepository.repository_id}
              >
                {namesById.get(taskRepository.repository_id) ?? taskRepository.repository_id}
              </div>
              <Badge>{REPOSITORY_ROLE_LABEL[taskRepository.role]}</Badge>
              <div className="flex w-full items-center gap-1.5 font-mono text-meta text-text-3">
                <GitBranch className="size-3" />
                {taskRepository.branch_name} ← {taskRepository.base_branch}
                <span className="ml-auto font-sans">
                  {MERGE_STATUS_LABELS[taskRepository.merge_status]}
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          compact
          title="Репозитории не привязаны"
          hint="Репозитории выбираются при создании задачи. Чтобы работать с другим набором, создайте задачу заново или продублируйте эту."
        />
      )}
    </Card>
  );
}
