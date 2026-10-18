import { useState } from "react";
import { CircleCheck, CircleX, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { McpServerForm } from "@/components/admin/McpServerForm";
import { useDeleteMcpServer, useMcpServers } from "@/hooks/useMcpServers";
import { ApiError } from "@/lib/apiClient";
import type { McpServer } from "@/lib/types";

export function McpServersPanel() {
  const { data: servers, isLoading } = useMcpServers();
  const deleteServer = useDeleteMcpServer();
  const [dialogServer, setDialogServer] = useState<McpServer | "new" | null>(null);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div className="text-[12.5px] font-extrabold text-text-2">MCP-серверы</div>
        <Button size="sm" onClick={() => setDialogServer("new")}>
          <Plus className="size-3.5" /> Сервер
        </Button>
      </div>
      {isLoading && <div className="text-text-3">Загрузка…</div>}
      {(servers ?? []).map((server) => (
        <Card key={server.id} className="flex items-center gap-3">
          {server.is_healthy ? (
            <CircleCheck className="size-4 shrink-0 text-success" />
          ) : (
            <CircleX className="size-4 shrink-0 text-danger" />
          )}
          <button className="min-w-0 flex-1 text-left" onClick={() => setDialogServer(server)}>
            <div className="truncate font-bold">{server.name}</div>
            <div className="truncate text-[12px] text-text-3">{server.url}</div>
          </button>
          {server.has_stateful_resource && (
            <Badge tone="warning">{server.isolation_mode}</Badge>
          )}
          <button
            type="button"
            onClick={() =>
              deleteServer.mutate(server.id, {
                onError: (error) =>
                  toast.error(error instanceof ApiError ? error.message : "Не удалось удалить"),
              })
            }
            className="touch-target flex items-center justify-center text-text-3 hover:text-danger"
          >
            <Trash2 className="size-4" />
          </button>
        </Card>
      ))}

      <Dialog open={dialogServer !== null} onOpenChange={(open) => !open && setDialogServer(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dialogServer === "new" ? "Новый MCP-сервер" : "Редактировать MCP-сервер"}
            </DialogTitle>
          </DialogHeader>
          {dialogServer !== null && (
            <McpServerForm
              server={dialogServer === "new" ? undefined : dialogServer}
              onSaved={() => setDialogServer(null)}
              onCancel={() => setDialogServer(null)}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
