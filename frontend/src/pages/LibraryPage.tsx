import { useState } from "react";
import { BookOpen, Plus } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { NodeForm } from "@/components/nodes/NodeForm";
import { NodeTypeIcon } from "@/components/tasks/NodeTypeIcon";
import { NODE_TYPE_LABEL } from "@/lib/labels";
import { useDeleteNode, useNodes } from "@/hooks/useNodes";
import { ApiError } from "@/lib/apiClient";
import type { NodeItem } from "@/lib/types";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";
import { LoadingState } from "@/components/common/feedback/LoadingState";

export function LibraryPage() {
  const { data: nodes, isLoading } = useNodes({ libraryOnly: true });
  const deleteNode = useDeleteNode();
  const [dialogNode, setDialogNode] = useState<NodeItem | "new" | null>(null);

  return (
    <div className={PAGE_ROOT}>
      <PageHeader
        title="Библиотека промтов"
        actions={
          <Button onClick={() => setDialogNode("new")}>
            <Plus className="size-4" /> Промт
          </Button>
        }
      />
      <div className={PAGE_BODY}>
        {isLoading && <LoadingState />}
        <div className="flex flex-col gap-2">
          {(nodes ?? []).map((node) => (
            <Card key={node.id} className="flex items-center gap-3">
              <NodeTypeIcon type={node.node_type} className="size-4 shrink-0 text-text-2" />
              <button className="min-h-11 min-w-0 flex-1 text-left" onClick={() => setDialogNode(node)}>
                <div className="truncate font-bold" title={node.name}>{node.name}</div>
                <div className="truncate text-small text-text-3" title={node.description ?? undefined}>{node.description}</div>
                <div className="text-caption font-bold uppercase text-text-3">
                  {NODE_TYPE_LABEL[node.node_type]}
                </div>
              </button>
              <ConfirmDeleteButton
                kind="промт"
                name={node.name}
                pending={deleteNode.isPending}
                onConfirm={() =>
                  deleteNode.mutate(node.id, {
                    onError: (error) =>
                      toast.error(
                        error instanceof ApiError ? error.message : "Не удалось удалить",
                      ),
                  })}
              />
            </Card>
          ))}
          {!isLoading && (nodes ?? []).length === 0 && (
            <EmptyState
              icon={BookOpen}
              title="Библиотека промтов пуста"
              hint="Нажмите «+ Промт» вверху справа, чтобы сохранить промт, слэш-команду или скрипт. Сохранённый промт можно добавить в любую задачу и запускать вручную кнопкой ▶."
            />
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
