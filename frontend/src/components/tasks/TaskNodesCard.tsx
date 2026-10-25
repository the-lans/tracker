import { Fragment, useState } from "react";
import { Lock, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/common/dialogs/ConfirmDialog";
import { DependentNodesDialog } from "@/components/tasks/DependentNodesDialog";
import {
  TaskCustomNodeDialog,
  type CustomNodeTarget,
} from "@/components/tasks/TaskCustomNodeDialog";
import { TaskNodeRow } from "@/components/tasks/TaskNodeRow";
import { useDependentNodesGuard } from "@/hooks/useDependentNodesGuard";
import {
  useDeleteTaskNode,
  useTaskNodeDependents,
  useTaskNodes,
  useUpdateTaskNode,
} from "@/hooks/useTasks";
import { toastError } from "@/lib/errors";
import { insertOrderIndex, isPositionEditable } from "@/lib/taskNodes";
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
    return "Снимите галочку, чтобы пропустить ноду в этой задаче, или вставьте свой промт кнопкой «+ Промт»";
  if (status === TaskStatus.FAILED) {
    return "Пройденные и упавшая ноды уже выполнены — менять можно только ноды после точки сбоя. Чтобы сменить пайплайн, верните задачу в новые";
  }
  if (status === TaskStatus.DONE) {
    return "Задача завершена — чтобы сменить пайплайн и запустить заново, верните её в новые";
  }
  return "Состав нод заблокирован — задача уже запущена";
}

/** Раздел 13.1–13.3, 15.2: ноды задачи с чекбоксами включения и своими
 * промтами; при отключении ноды, на вывод которой ссылаются следующие, —
 * предупреждение. */
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
  const deleteTaskNode = useDeleteTaskNode(task.id);
  const [customTarget, setCustomTarget] = useState<CustomNodeTarget>(null);
  const [deleting, setDeleting] = useState<TaskNodeItem | null>(null);
  const nodes = taskNodes ?? [];

  function canInsertAfter(after: TaskNodeItem | null): boolean {
    return isPositionEditable(task, nodes, insertOrderIndex(nodes, after));
  }

  function confirmDelete() {
    if (!deleting) return;
    deleteTaskNode.mutate(deleting.id, {
      onSuccess: () => setDeleting(null),
      onError: toastError("Не удалось удалить свой промт"),
    });
  }

  function updateNode(
    taskNodeId: string,
    body: TaskNodeUpdateRequest,
    failure: string,
  ) {
    updateTaskNode.mutate(
      { taskNodeId, ...body },
      { onError: toastError(failure) },
    );
  }

  function toggleNode(taskNode: TaskNodeItem, isEnabled: boolean) {
    const setEnabled = () =>
      updateNode(
        taskNode.id,
        { is_enabled: isEnabled },
        "Не удалось изменить состав нод",
      );
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
          {taskNodes && canInsertAfter(null) && (
            <InsertPromptButton
              label="Вставить свой промт в начало"
              onClick={() => setCustomTarget({ kind: "insert", after: null })}
            />
          )}
          {nodes.map((taskNode) => (
            <Fragment key={taskNode.id}>
              <TaskNodeRow
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
                onEdit={() => setCustomTarget({ kind: "edit", taskNode })}
                onDelete={() => setDeleting(taskNode)}
              />
              {canInsertAfter(taskNode) && (
                <InsertPromptButton
                  label={`Вставить свой промт после ноды ${taskNode.name}`}
                  onClick={() =>
                    setCustomTarget({ kind: "insert", after: taskNode })
                  }
                />
              )}
            </Fragment>
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
      <TaskCustomNodeDialog
        taskId={task.id}
        taskNodes={nodes}
        target={customTarget}
        onClose={() => setCustomTarget(null)}
      />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title="Удалить свой промт?"
        description={`Промт «${deleting?.name ?? ""}» будет удалён из этой задачи. Если он уже выполнялся, удалить нельзя — его можно отключить.`}
        confirmLabel="Удалить"
        danger
        pending={deleteTaskNode.isPending}
        onConfirm={confirmDelete}
      />
    </>
  );
}

/** Раздел 15.2: вставка своего промта на это место состава. */
function InsertPromptButton({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="touch-hit flex items-center gap-1 self-start py-0.5 text-caption font-bold text-text-3 hover:text-accent"
    >
      <Plus className="size-3" />
      Промт
    </button>
  );
}
