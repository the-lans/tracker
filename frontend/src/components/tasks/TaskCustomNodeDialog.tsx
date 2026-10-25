import { TaskCustomNodeForm } from "@/components/tasks/TaskCustomNodeForm";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useCreateTaskNode, useUpdateTaskNode } from "@/hooks/useTasks";
import { toastError } from "@/lib/errors";
import { insertOrderIndex } from "@/lib/taskNodes";
import type { TaskCustomNodeContent, TaskNodeItem } from "@/lib/types";

/** Что открыто: вставка после ноды (`after: null` — в начало) или правка своей ноды. */
export type CustomNodeTarget =
  | { kind: "insert"; after: TaskNodeItem | null }
  | { kind: "edit"; taskNode: TaskNodeItem }
  | null;

/** Раздел 13.1, 15.2: диалог вставки и правки своего промта задачи. */
export function TaskCustomNodeDialog({
  taskId,
  taskNodes,
  target,
  onClose,
}: {
  taskId: string;
  taskNodes: TaskNodeItem[];
  target: CustomNodeTarget;
  onClose: () => void;
}) {
  const createTaskNode = useCreateTaskNode(taskId);
  const updateTaskNode = useUpdateTaskNode(taskId);
  const callbacks = {
    onSuccess: onClose,
    onError: toastError("Не удалось сохранить свой промт"),
  };

  function handleSubmit(content: TaskCustomNodeContent) {
    if (target?.kind === "edit") {
      updateTaskNode.mutate(
        { taskNodeId: target.taskNode.id, content },
        callbacks,
      );
    } else if (target?.kind === "insert") {
      createTaskNode.mutate(
        { ...content, after_task_node_id: target.after?.id ?? null },
        callbacks,
      );
    }
  }

  const editing = target?.kind === "edit" ? target.taskNode : undefined;
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>
            {editing ? "Изменить свой промт" : "Свой промт"}
          </DialogTitle>
        </DialogHeader>
        {target !== null && (
          <TaskCustomNodeForm
            taskId={taskId}
            orderIndex={
              editing
                ? editing.order_index
                : insertOrderIndex(
                    taskNodes,
                    target.kind === "insert" ? target.after : null,
                  )
            }
            initial={
              editing && {
                name: editing.name,
                node_type: editing.node_type,
                prompt_template: editing.prompt_template,
                command_invocation: editing.command_invocation,
              }
            }
            nodeId={editing?.node_id}
            pending={createTaskNode.isPending || updateTaskNode.isPending}
            onSubmit={handleSubmit}
            onCancel={onClose}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
