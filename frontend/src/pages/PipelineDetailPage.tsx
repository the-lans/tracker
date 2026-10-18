import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { NodeForm } from "@/components/nodes/NodeForm";
import { NodeTypeIcon, NODE_TYPE_LABEL } from "@/components/tasks/NodeTypeIcon";
import { usePipeline, usePipelineNodes } from "@/hooks/usePipelines";
import { useDeleteNode, useUpdateNode } from "@/hooks/useNodes";
import { ApiError } from "@/lib/apiClient";
import type { NodeItem } from "@/lib/types";

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
  const [dialogNode, setDialogNode] = useState<NodeItem | "new" | null>(null);

  const sorted = [...(nodes ?? [])].sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0));
  const nextOrderIndex = sorted.length > 0 ? (sorted[sorted.length - 1]!.order_index ?? 0) + 1 : 0;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-border bg-surface px-5 py-3 lg:px-8">
        <Link
          to="/pipelines"
          className="flex touch-target size-8 shrink-0 items-center justify-center rounded-[9px] border border-border text-text-2"
        >
          <ArrowLeft className="size-4" />
        </Link>
        <h1 className="text-[17px] font-extrabold">{pipeline?.name ?? "Пайплайн"}</h1>
        <Button className="ml-auto" onClick={() => setDialogNode("new")}>
          <Plus className="size-4" /> Нода
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-5 py-5 lg:px-8">
        {isLoading && <div className="text-text-3">Загрузка…</div>}
        <div className="flex max-w-2xl flex-col gap-2">
          {sorted.map((node, index) => (
            <Card key={node.id} className="flex items-center gap-3">
              <span className="w-5 shrink-0 text-center text-[12px] font-bold text-text-3">
                {index + 1}
              </span>
              <NodeTypeIcon type={node.node_type} className="size-4 shrink-0 text-text-2" />
              <button className="min-w-0 flex-1 text-left" onClick={() => setDialogNode(node)}>
                <div className="truncate font-bold">{node.name}</div>
              </button>
              <span className="text-[11px] font-bold uppercase text-text-3">
                {NODE_TYPE_LABEL[node.node_type]}
              </span>
              <ReorderButtons node={node} neighbor={sorted[index - 1]} />
              <ReorderButtons node={node} neighbor={sorted[index + 1]} />
              <button
                type="button"
                onClick={() =>
                  deleteNode.mutate(node.id, {
                    onError: (error) =>
                      toast.error(
                        error instanceof ApiError ? error.message : "Не удалось удалить ноду",
                      ),
                  })
                }
                className="touch-target flex items-center justify-center text-text-3 hover:text-danger"
                aria-label="Удалить"
              >
                <Trash2 className="size-4" />
              </button>
            </Card>
          ))}
          {!isLoading && sorted.length === 0 && (
            <div className="py-10 text-center text-text-3">В пайплайне пока нет нод</div>
          )}
        </div>
      </div>

      <Dialog open={dialogNode !== null} onOpenChange={(open) => !open && setDialogNode(null)}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>{dialogNode === "new" ? "Новая нода" : "Редактировать ноду"}</DialogTitle>
          </DialogHeader>
          {dialogNode !== null && pipelineId && (
            <NodeForm
              mode="pipeline"
              pipelineId={pipelineId}
              orderIndex={dialogNode === "new" ? nextOrderIndex : undefined}
              node={dialogNode === "new" ? undefined : dialogNode}
              onSaved={() => setDialogNode(null)}
              onCancel={() => setDialogNode(null)}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
