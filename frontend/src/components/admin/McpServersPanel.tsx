import { useState } from "react";
import { CircleCheck, CircleX, Plus, Server } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { McpServerForm } from "@/components/admin/McpServerForm";
import { useDeleteMcpServer, useMcpServers } from "@/hooks/useMcpServers";
import { toastError } from "@/lib/errors";
import type { McpServer } from "@/lib/types";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { EditButton } from "@/components/common/actions/EditButton";
import { MCP_ISOLATION_LABEL } from "@/lib/labels";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { SectionTitle } from "@/components/common/typography/SectionTitle";
import { EntityFormDialog, type EditTarget } from "@/components/common/dialogs/EntityFormDialog";

export function McpServersPanel() {
  const { data: servers, isLoading } = useMcpServers();
  const deleteServer = useDeleteMcpServer();
  const [dialogServer, setDialogServer] = useState<EditTarget<McpServer>>(null);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <SectionTitle>MCP-серверы</SectionTitle>
        <Button size="sm" onClick={() => setDialogServer("new")}>
          <Plus className="size-3.5" /> Сервер
        </Button>
      </div>
      {isLoading && <LoadingState />}
      {!isLoading && (servers ?? []).length === 0 && (
        <EmptyState
          icon={Server}
          title="MCP-серверов пока нет"
          hint="Нажмите «+ Сервер» выше и укажите адрес. Подключённый сервер добавляется в шаблон — тогда агент в задачах получает его инструменты."
        />
      )}
      {(servers ?? []).map((server) => (
        <Card key={server.id} className="flex items-center gap-3">
          {server.is_healthy ? (
            <CircleCheck className="size-4 shrink-0 text-success" />
          ) : (
            <CircleX className="size-4 shrink-0 text-danger" />
          )}
          <div className="min-w-0 flex-1">
            <div className="truncate font-bold" title={server.name}>{server.name}</div>
            <div className="truncate text-small text-text-3" title={server.url}>{server.url}</div>
            {server.has_stateful_resource && (
              <Badge tone="warning" className="mt-1">
                {server.isolation_mode ? MCP_ISOLATION_LABEL[server.isolation_mode] : "изоляция не выбрана"}
              </Badge>
            )}
          </div>
          <EditButton name={server.name} onClick={() => setDialogServer(server)} />
          <ConfirmDeleteButton
            kind="MCP-сервер"
            name={server.name}
            pending={deleteServer.isPending}
            onConfirm={() =>
              deleteServer.mutate(server.id, {
                onError: toastError("Не удалось удалить"),
              })}
          />
        </Card>
      ))}

      <EntityFormDialog
        target={dialogServer}
        onClose={() => setDialogServer(null)}
        createTitle="Новый MCP-сервер"
        editTitle="Редактировать MCP-сервер"
      >
        {(item, close) => (
          <McpServerForm
            server={item}
            onSaved={close}
            onCancel={close}
          />
        )}
      </EntityFormDialog>
    </div>
  );
}
