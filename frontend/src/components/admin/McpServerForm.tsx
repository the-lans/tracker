import { useState } from "react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DialogFooter } from "@/components/ui/dialog";
import { useCreateMcpServer, useUpdateMcpServer } from "@/hooks/useMcpServers";
import { ApiError } from "@/lib/apiClient";
import { McpAuthType, McpIsolationMode, type McpServer } from "@/lib/types";
import { MCP_ISOLATION_LABEL } from "@/lib/labels";

const REQUIRED_PATH_VARIABLE = "{{task.repos_path}}";

export function McpServerForm({
  server,
  onSaved,
  onCancel,
}: {
  server?: McpServer;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const createServer = useCreateMcpServer();
  const updateServer = useUpdateMcpServer(server?.id ?? "");

  const [name, setName] = useState(server?.name ?? "");
  const [url, setUrl] = useState(server?.url ?? "");
  const [authType, setAuthType] = useState<McpAuthType>(server?.auth_type ?? McpAuthType.NONE);
  const [authConfig, setAuthConfig] = useState("");
  const [hasStatefulResource, setHasStatefulResource] = useState(server?.has_stateful_resource ?? false);
  const [isolationMode, setIsolationMode] = useState<McpIsolationMode | "">(
    server?.isolation_mode ?? "",
  );
  const [isolationPathTemplate, setIsolationPathTemplate] = useState(
    server?.isolation_path_template ?? "",
  );

  // Раздел 15.5, правило 3 CLAUDE.md: сохранение блокируется, пока для
  // has_stateful_resource=true не выбран isolation_mode (и, для
  // per_task_data_dir, не заполнен путь с нужной переменной) — проверяется
  // здесь же, до отправки на backend, который продублирует ту же проверку.
  const isolationError = hasStatefulResource
    ? isolationMode === "" || isolationMode === McpIsolationMode.NONE
      ? "Выберите режим изоляции"
      : isolationMode === McpIsolationMode.PER_TASK_DATA_DIR &&
          !isolationPathTemplate.includes(REQUIRED_PATH_VARIABLE)
        ? `isolation_path_template должен содержать ${REQUIRED_PATH_VARIABLE}`
        : null
    : null;

  function handleSave() {
    const body = {
      name,
      url,
      auth_type: authType,
      ...(authConfig ? { auth_config: authConfig } : {}),
      has_stateful_resource: hasStatefulResource,
      isolation_mode: hasStatefulResource ? (isolationMode as McpIsolationMode) : null,
      isolation_path_template: hasStatefulResource ? isolationPathTemplate : null,
    };
    const onError = (error: unknown) =>
      toast.error(error instanceof ApiError ? error.message : "Не удалось сохранить сервер");

    if (server) {
      updateServer.mutate(body, { onSuccess: onSaved, onError });
    } else {
      createServer.mutate({ ...body, auth_config: authConfig }, { onSuccess: onSaved, onError });
    }
  }

  const isPending = createServer.isPending || updateServer.isPending;

  return (
    <div className="flex flex-col gap-3">
      <div>
        <Label htmlFor="mcp-name">Название</Label>
        <Input id="mcp-name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div>
        <Label htmlFor="mcp-url">URL</Label>
        <Input id="mcp-url" value={url} onChange={(e) => setUrl(e.target.value)} />
      </div>
      <div>
        <Label>Тип авторизации</Label>
        <Select value={authType} onValueChange={(v) => setAuthType(v as McpAuthType)}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={McpAuthType.NONE}>Без авторизации</SelectItem>
            <SelectItem value={McpAuthType.API_KEY}>API-ключ</SelectItem>
            <SelectItem value={McpAuthType.BEARER_TOKEN}>Bearer-токен</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {authType !== McpAuthType.NONE && (
        <div>
          <Label htmlFor="mcp-auth-config">
            {server ? "Новое значение (оставьте пустым, чтобы не менять)" : "Ключ/токен"}
          </Label>
          <Input
            id="mcp-auth-config"
            type="password"
            value={authConfig}
            onChange={(e) => setAuthConfig(e.target.value)}
          />
        </div>
      )}
      <div className="flex items-center justify-between rounded-md border border-border p-3">
        <div>
          <div className="text-body font-bold">Ресурс с состоянием</div>
          <div className="text-meta text-text-3">Сервер держит состояние между вызовами</div>
        </div>
        <Switch checked={hasStatefulResource} onCheckedChange={setHasStatefulResource} />
      </div>
      {hasStatefulResource && (
        <>
          <div>
            <Label>Режим изоляции</Label>
            <Select
              value={isolationMode}
              onValueChange={(v) => setIsolationMode(v as McpIsolationMode)}
            >
              <SelectTrigger>
                <SelectValue placeholder="Выберите режим" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={McpIsolationMode.ISOLATED_FLAG}>
                  {MCP_ISOLATION_LABEL[McpIsolationMode.ISOLATED_FLAG]}
                </SelectItem>
                <SelectItem value={McpIsolationMode.PER_TASK_DATA_DIR}>
                  {MCP_ISOLATION_LABEL[McpIsolationMode.PER_TASK_DATA_DIR]}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          {isolationMode === McpIsolationMode.PER_TASK_DATA_DIR && (
            <div>
              <Label htmlFor="mcp-path">Шаблон пути профиля</Label>
              <Input
                id="mcp-path"
                placeholder="{{task.repos_path}}/.mcp-profiles/playwright"
                value={isolationPathTemplate}
                onChange={(e) => setIsolationPathTemplate(e.target.value)}
              />
            </div>
          )}
          {isolationError && <div className="text-small text-danger-text">{isolationError}</div>}
        </>
      )}
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button
          type="button"
          onClick={handleSave}
          disabled={!name || !url || Boolean(isolationError) || isPending}
        >
          Сохранить
        </Button>
      </DialogFooter>
    </div>
  );
}
