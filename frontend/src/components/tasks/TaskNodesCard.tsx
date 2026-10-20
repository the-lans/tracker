import { Check, Lock } from "lucide-react";
import { toast } from "sonner";
import { Card, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { DependentNodesDialog } from "@/components/tasks/DependentNodesDialog";
import { NodeTypeIcon } from "@/components/tasks/NodeTypeIcon";
import { NODE_TYPE_LABEL } from "@/lib/labels";
import { useDependentNodesGuard } from "@/hooks/useDependentNodesGuard";
import {
  useSetTaskNodeEnabled,
  useTaskNodeDependents,
  useTaskNodes,
} from "@/hooks/useTasks";
import { ApiError } from "@/lib/apiClient";
import { cn } from "@/lib/utils";
import {
  TaskStatus,
  type NodeLog,
  type Task,
  type TaskNodeItem,
} from "@/lib/types";
import { EmptyState } from "@/components/common/feedback/EmptyState";

/** Раздел 13.2, 15.2: пояснение к блокировке чекбоксов нод. */
function nodesHint(status: TaskStatus): string {
  if (status === TaskStatus.NEW)
    return "Снимите галочку, чтобы пропустить ноду в этой задаче";
  if (status === TaskStatus.FAILED) {
    return "Пройденные и упавшая ноды уже выполнены — менять можно только ноды после точки сбоя";
  }
  return "Состав нод заблокирован — задача уже запущена";
}

/** Раздел 13.1–13.3, 15.2: ноды задачи с чекбоксами включения; при
 * отключении ноды, на вывод которой ссылаются следующие, — предупреждение. */
export function TaskNodesCard({
  task,
  nodeLogs,
}: {
  task: Task;
  nodeLogs: NodeLog[];
}) {
  const { data: taskNodes } = useTaskNodes(task.id, true);
  const setTaskNodeEnabled = useSetTaskNodeEnabled(task.id);
  const taskNodeDependents = useTaskNodeDependents(task.id);
  const dependentsGuard = useDependentNodesGuard();

  function setNodeEnabled(taskNodeId: string, isEnabled: boolean) {
    setTaskNodeEnabled.mutate(
      { taskNodeId, isEnabled },
      {
        onError: (error) => {
          toast.error(
            error instanceof ApiError
              ? error.message
              : "Не удалось изменить состав нод",
          );
        },
      },
    );
  }

  function toggleNode(taskNode: TaskNodeItem, isEnabled: boolean) {
    if (isEnabled) {
      setNodeEnabled(taskNode.id, true);
      return;
    }
    void dependentsGuard.guard(
      taskNode.name,
      () => taskNodeDependents.mutateAsync(taskNode.id),
      () => setNodeEnabled(taskNode.id, false),
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
          {taskNodes && (
            <span>
              {successfulPipelineNodeIds.size} /{" "}
              {taskNodes.filter((node) => node.is_enabled).length}
            </span>
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
          {(taskNodes ?? []).map((taskNode) => {
            const done = successfulPipelineNodeIds.has(taskNode.node_id);
            const isCurrent = taskNode.node_id === currentNodeId;
            return (
              <label
                key={taskNode.id}
                className={cn(
                  "flex items-center gap-2.5 border-t border-border py-2 first:border-t-0",
                  isCurrent &&
                    "-mx-2 rounded-lg border-t-0 bg-accent-tint px-2",
                  !taskNode.is_enabled && "text-text-3",
                )}
              >
                <Checkbox
                  checked={taskNode.is_enabled}
                  disabled={
                    !taskNode.editable ||
                    setTaskNodeEnabled.isPending ||
                    taskNodeDependents.isPending
                  }
                  aria-label={`Включить ноду ${taskNode.name}`}
                  onCheckedChange={(checked) =>
                    toggleNode(taskNode, checked === true)
                  }
                />
                <NodeTypeIcon
                  type={taskNode.node_type}
                  className="size-[15px] shrink-0 text-text-2"
                />
                <div className="min-w-0 flex-1 truncate text-note font-bold" title={taskNode.name}>
                  {taskNode.name}
                </div>
                {done ? (
                  <Check
                    className="size-3.5 shrink-0 text-success"
                    aria-label="выполнено"
                  />
                ) : (
                  <div className="text-caption font-bold uppercase tracking-wide text-text-3">
                    {NODE_TYPE_LABEL[taskNode.node_type]}
                  </div>
                )}
              </label>
            );
          })}
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
