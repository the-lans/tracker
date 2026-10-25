import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowDown, ArrowLeft, ArrowUp, Layers, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { NodeForm } from "@/components/nodes/NodeForm";
import { NodeTypeIcon } from "@/components/tasks/NodeTypeIcon";
import { NODE_TYPE_LABEL } from "@/lib/labels";
import { usePipeline, usePipelineNodes } from "@/hooks/usePipelines";
import { useDeleteNode, useUpdateNode } from "@/hooks/useNodes";
import { errorMessage } from "@/lib/errors";
import type { NodeItem } from "@/lib/types";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";
import { cn } from "@/lib/utils";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { EntityFormDialog, type EditTarget } from "@/components/common/dialogs/EntityFormDialog";

function ReorderButtons({ node, neighbor }: { node: NodeItem; neighbor?: NodeItem }) {
  const updateThis = useUpdateNode(node.id);
  const updateNeighbor = useUpdateNode(neighbor?.id ?? "");

  function swap() {
    if (!neighbor) return;
    updateThis.mutate({ order_index: neighbor.order_index ?? 0 });
    updateNeighbor.mutate({ order_index: node.order_index ?? 0 });
  }

  return (
    <button
      type="button"
      disabled={!neighbor}
      onClick={swap}
      className="touch-target flex items-center justify-center text-text-3 hover:text-text disabled:opacity-30"
    >
      {neighbor && neighbor.order_index! < node.order_index! ? (
        <ArrowUp className="size-4" />
      ) : (
        <ArrowDown className="size-4" />
      )}
    </button>
  );
}

export function PipelineDetailPage() {
  const { pipelineId } = useParams<{ pipelineId: string }>();
  const { data: pipeline } = usePipeline(pipelineId);
  const { data: nodes, isLoading } = usePipelineNodes(pipelineId);
  const deleteNode = useDeleteNode();
  const [dialogNode, setDialogNode] = useState<EditTarget<NodeItem>>(null);

  const sorted = [...(nodes ?? [])].sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0));
  const nextOrderIndex = sorted.length > 0 ? (sorted[sorted.length - 1]!.order_index ?? 0) + 1 : 0;

  return (
    <div className={PAGE_ROOT}>
      <div className="flex items-center gap-3 border-b border-border bg-surface px-5 py-3 lg:px-8">
        <Link
          to="/pipelines"
          className="flex touch-target size-8 shrink-0 items-center justify-center rounded-[9px] border border-border text-text-2"
        >
          <ArrowLeft className="size-4" />
        </Link>
        <h1 className="text-heading font-extrabold">{pipeline?.name ?? "Пайплайн"}</h1>
        <Button className="ml-auto" onClick={() => setDialogNode("new")}>
          <Plus className="size-4" /> Нода
        </Button>
      </div>

      <div className={cn(PAGE_BODY, "py-5")}>
        {isLoading && <LoadingState />}
        <div className="flex max-w-2xl flex-col gap-2">
          {sorted.map((node, index) => (
            <Card key={node.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="w-5 shrink-0 text-center text-small font-bold text-text-3">
                {index + 1}
              </span>
              <NodeTypeIcon type={node.node_type} className="size-4 shrink-0 text-text-2" />
              <button className="min-h-11 min-w-0 flex-1 basis-40 text-left" onClick={() => setDialogNode(node)}>
                <div className="truncate font-bold" title={node.name}>{node.name}</div>
                <div className="text-caption font-bold uppercase text-text-3">
                  {NODE_TYPE_LABEL[node.node_type]}
                </div>
              </button>
              <div className="ml-auto flex shrink-0 items-center">
              <ReorderButtons node={node} neighbor={sorted[index - 1]} />
              <ReorderButtons node={node} neighbor={sorted[index + 1]} />
              <ConfirmDeleteButton
                kind="ноду"
                name={node.name}
                pending={deleteNode.isPending}
                onConfirm={() =>
                  deleteNode.mutate(node.id, {
                    onError: (error) =>
                      toast.error(
                        errorMessage(error, "Не удалось удалить ноду"),
                      ),
                  })}
              />
              </div>
            </Card>
          ))}
          {!isLoading && sorted.length === 0 && (
            <EmptyState
              icon={Layers}
              title="В пайплайне пока нет нод"
              hint="Нажмите «+ Нода» вверху справа и выберите тип: промт, слэш-команда, скрипт, режим планирования или очистка контекста. Ноды выполняются сверху вниз, порядок меняется стрелками."
            />
          )}
        </div>
      </div>

      <EntityFormDialog
        target={dialogNode}
        onClose={() => setDialogNode(null)}
        createTitle="Новая нода"
        editTitle="Редактировать ноду"
        contentClassName="max-w-xl"
      >
        {(item, close) =>
          pipelineId && (
            <NodeForm
              mode="pipeline"
              pipelineId={pipelineId}
              orderIndex={item === undefined ? nextOrderIndex : undefined}
              node={item}
              onSaved={close}
              onCancel={close}
            />
          )
        }
      </EntityFormDialog>
    </div>
  );
}
