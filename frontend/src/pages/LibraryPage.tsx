import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { NodeForm } from "@/components/nodes/NodeForm";
import { NodeTypeIcon, NODE_TYPE_LABEL } from "@/components/tasks/NodeTypeIcon";
import { useDeleteNode, useNodes } from "@/hooks/useNodes";
import { ApiError } from "@/lib/apiClient";
import type { NodeItem } from "@/lib/types";

export function LibraryPage() {
  const { data: nodes, isLoading } = useNodes({ libraryOnly: true });
  const deleteNode = useDeleteNode();
  const [dialogNode, setDialogNode] = useState<NodeItem | "new" | null>(null);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Библиотека промтов"
        actions={
          <Button onClick={() => setDialogNode("new")}>
            <Plus className="size-4" /> Промт
          </Button>
        }
      />
      <div className="min-h-0 flex-1 overflow-auto px-5 pb-8 lg:px-8">
        {isLoading && <div className="text-text-3">Загрузка…</div>}
        <div className="flex flex-col gap-2">
          {(nodes ?? []).map((node) => (
            <Card key={node.id} className="flex items-center gap-3">
              <NodeTypeIcon type={node.node_type} className="size-4 shrink-0 text-text-2" />
              <button className="min-w-0 flex-1 text-left" onClick={() => setDialogNode(node)}>
                <div className="truncate font-bold">{node.name}</div>
                <div className="truncate text-[12px] text-text-3">{node.description}</div>
              </button>
              <span className="text-[11px] font-bold uppercase text-text-3">
                {NODE_TYPE_LABEL[node.node_type]}
              </span>
              <button
                type="button"
                onClick={() =>
                  deleteNode.mutate(node.id, {
                    onError: (error) =>
                      toast.error(
                        error instanceof ApiError ? error.message : "Не удалось удалить",
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
          {!isLoading && (nodes ?? []).length === 0 && (
            <div className="py-10 text-center text-text-3">Библиотека промтов пуста</div>
          )}
        </div>
      </div>

      <Dialog open={dialogNode !== null} onOpenChange={(open) => !open && setDialogNode(null)}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>
              {dialogNode === "new" ? "Новый промт библиотеки" : "Редактировать промт"}
            </DialogTitle>
          </DialogHeader>
          {dialogNode !== null && (
            <NodeForm
              mode="library"
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
