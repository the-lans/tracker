import { useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { DependentNodesDialog } from "@/components/tasks/DependentNodesDialog";
import { PipelineNodesChecklist } from "@/components/tasks/PipelineNodesChecklist";
import { useDependentNodesGuard } from "@/hooks/useDependentNodesGuard";
import { usePipelineNodeDependents, usePipelineNodes, usePipelines } from "@/hooks/usePipelines";
import { useBindPipeline } from "@/hooks/useTasks";
import { ApiError } from "@/lib/apiClient";
import type { NodeItem, Task } from "@/lib/types";
import { EmptyState } from "@/components/common/feedback/EmptyState";

/** Раздел 1.2 (сценарий 2), 13.1: выбор пайплайна сразу с составом нод —
 * по умолчанию включены все, кроме нод с «пропуском по умолчанию». */
export function PipelinePickerDialog({
  task,
  open,
  onOpenChange,
}: {
  task: Task;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data: pipelines } = usePipelines();
  const bindPipeline = useBindPipeline(task.id);
  const [pipelineId, setPipelineId] = useState("");
  // Только явные изменения пользователя; остальное — по `is_skipped`.
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});
  const { data: nodes } = usePipelineNodes(pipelineId || undefined);
  const pipelineDependents = usePipelineNodeDependents(pipelineId);
  const dependentsGuard = useDependentNodesGuard();

  const isEnabled = (node: NodeItem) => overrides[node.id] ?? !node.is_skipped;
  const orderedNodes = [...(nodes ?? [])].sort(
    (left, right) => (left.order_index ?? 0) - (right.order_index ?? 0),
  );

  function selectPipeline(id: string) {
    setPipelineId(id);
    setOverrides({});
  }

  function setNodeEnabled(node: NodeItem, enabled: boolean) {
    setOverrides((prev) => ({ ...prev, [node.id]: enabled }));
  }

  function toggleNode(node: NodeItem, enabled: boolean) {
    if (enabled) {
      setNodeEnabled(node, true);
      return;
    }
    const enabledNodeIds = orderedNodes.filter(isEnabled).map((item) => item.id);
    void dependentsGuard.guard(
      node.name,
      () =>
        pipelineDependents.mutateAsync({ node_id: node.id, enabled_node_ids: enabledNodeIds }),
      () => setNodeEnabled(node, false),
    );
  }

  function handleBind() {
    if (!pipelineId) return;
    const disabledNodeIds = orderedNodes.filter((node) => !isEnabled(node)).map((node) => node.id);
    bindPipeline.mutate(
      { pipeline_id: pipelineId, disabled_node_ids: disabledNodeIds },
      {
        onSuccess: () => onOpenChange(false),
        onError: (error) => {
          toast.error(error instanceof ApiError ? error.message : "Не удалось привязать пайплайн");
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Выбрать пайплайн</DialogTitle>
        </DialogHeader>
        <Select value={pipelineId} onValueChange={selectPipeline}>
          <SelectTrigger>
            <SelectValue placeholder="Выберите пайплайн" />
          </SelectTrigger>
          <SelectContent>
            {(pipelines ?? []).map((pipeline) => (
              <SelectItem key={pipeline.id} value={pipeline.id}>
                {pipeline.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {pipelines && pipelines.length === 0 && (
          <EmptyState
            compact
            title="Пайплайнов пока нет"
            hint="Создайте пайплайн в разделе «Пайплайны» кнопкой «+ Пайплайн» и добавьте в него ноды, затем вернитесь сюда."
          />
        )}
        {pipelineId && nodes && nodes.length === 0 && (
          <EmptyState
            compact
            title="В этом пайплайне нет нод"
            hint="Задаче нечего выполнять. Добавьте ноды в разделе «Пайплайны» кнопкой «+ Нода» или выберите другой пайплайн."
          />
        )}
        {orderedNodes.length > 0 && (
          <PipelineNodesChecklist
            nodes={orderedNodes}
            isEnabled={isEnabled}
            disabled={pipelineDependents.isPending}
            onToggle={toggleNode}
          />
        )}
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button onClick={handleBind} disabled={!pipelineId || bindPipeline.isPending}>
            Привязать
          </Button>
        </DialogFooter>
        {/* Вложенный диалог — внутри родительского, чтобы не конфликтовали ловушки фокуса. */}
        <DependentNodesDialog
          pending={dependentsGuard.pending}
          onConfirm={dependentsGuard.confirm}
          onCancel={dependentsGuard.cancel}
        />
      </DialogContent>
    </Dialog>
  );
}
