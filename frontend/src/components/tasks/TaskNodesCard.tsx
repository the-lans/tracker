import { Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { DependentNodesDialog } from "@/components/tasks/DependentNodesDialog";
import { TaskNodeRow } from "@/components/tasks/TaskNodeRow";
import { useDependentNodesGuard } from "@/hooks/useDependentNodesGuard";
import { useTaskNodeDependents, useTaskNodes, useUpdateTaskNode } from "@/hooks/useTasks";
import { toastError } from "@/lib/errors";
import {
  TaskStatus,
  type NodeLog,
  type Task,
  type TaskNodeItem,
  type TaskNodeUpdateRequest,
} from "@/lib/types";
import { EmptyState } from "@/components/common/feedback/EmptyState";

/** Раздел 13.2, 15.2: пояснение к блокировке чекбоксов нод. */
function nodesHint(status: TaskStatus): string {
  if (status === TaskStatus.NEW)
    return "Снимите галочку, чтобы пропустить ноду в этой задаче";
  if (status === TaskStatus.FAILED) {
    return "Пройденные и упавшая ноды уже выполнены — менять можно только ноды после точки сбоя. Чтобы сменить пайплайн, верните задачу в новые";
  }
  if (status === TaskStatus.DONE) {
    return "Задача завершена — чтобы сменить пайплайн и запустить заново, верните её в новые";
  }
  return "Состав нод заблокирован — задача уже запущена";
}

/** Раздел 13.1–13.3, 15.2: ноды задачи с чекбоксами включения; при
 * отключении ноды, на вывод которой ссылаются следующие, — предупреждение. */
export function TaskNodesCard({
  task,
  nodeLogs,
  onChangePipeline,
}: {
  task: Task;
  nodeLogs: NodeLog[];
  /** Раздел 13.1: до запуска пайплайн можно сменить. */
  onChangePipeline: () => void;
}) {
  const { data: taskNodes } = useTaskNodes(task.id, true);
  const updateTaskNode = useUpdateTaskNode(task.id);
  const taskNodeDependents = useTaskNodeDependents(task.id);
  const dependentsGuard = useDependentNodesGuard();

  function updateNode(taskNodeId: string, body: TaskNodeUpdateRequest, failure: string) {
    updateTaskNode.mutate({ taskNodeId, ...body }, { onError: toastError(failure) });
  }

  function toggleNode(taskNode: TaskNodeItem, isEnabled: boolean) {
    const setEnabled = () =>
      updateNode(taskNode.id, { is_enabled: isEnabled }, "Не удалось изменить состав нод");
    if (isEnabled) {
      setEnabled();
      return;
    }
    void dependentsGuard.guard(
      taskNode.name,
      () => taskNodeDependents.mutateAsync(taskNode.id),
      setEnabled,
    );
  }

  const successfulPipelineNodeIds = new Set(
    nodeLogs
      .filter((log) => log.status === "success" && log.node_id)
      .map((log) => log.node_id),
  );
  const currentNodeId = [...nodeLogs]
    .reverse()
    .find(
      (log) => log.status === "running" || log.status === "awaiting_decision",
    )?.node_id;

  return (
    <>
      <Card>
        <CardTitle>
          <span>Ноды пайплайна</span>
          {task.status === TaskStatus.NEW ? (
            <Button size="sm" variant="secondary" onClick={onChangePipeline}>
              Сменить пайплайн
            </Button>
          ) : (
            taskNodes && (
              <span>
                {successfulPipelineNodeIds.size} /{" "}
                {taskNodes.filter((node) => node.is_enabled).length}
              </span>
            )
          )}
        </CardTitle>
        <div className="flex flex-col">
          {taskNodes && taskNodes.length === 0 && (
            <EmptyState
              compact
              title="В пайплайне нет нод"
              hint="Пайплайн был пуст в момент привязки, поэтому задаче нечего выполнять. Добавьте ноды в разделе «Пайплайны» кнопкой «+ Нода» и создайте задачу заново."
            />
          )}
          {(taskNodes ?? []).map((taskNode) => (
            <TaskNodeRow
              key={taskNode.id}
              taskNode={taskNode}
              done={successfulPipelineNodeIds.has(taskNode.node_id)}
              isCurrent={taskNode.node_id === currentNodeId}
              busy={updateTaskNode.isPending || taskNodeDependents.isPending}
              onToggleEnabled={(isEnabled) => toggleNode(taskNode, isEnabled)}
              onTogglePause={(pauseAfter) =>
                updateNode(
                  taskNode.id,
                  { pause_after: pauseAfter },
                  "Не удалось изменить паузу после ноды",
                )
              }
            />
          ))}
        </div>
        <div className="mt-2 flex items-center gap-1.5 text-caption text-text-3">
          <Lock className="size-3" />
          {nodesHint(task.status)}
        </div>
      </Card>
      <DependentNodesDialog
        pending={dependentsGuard.pending}
        onConfirm={dependentsGuard.confirm}
        onCancel={dependentsGuard.cancel}
      />
    </>
  );
}
