import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { DialogFooter } from "@/components/ui/dialog";
import { useCreateTemplate, useUpdateTemplate } from "@/hooks/useTemplates";
import { useMcpServers } from "@/hooks/useMcpServers";
import { useAuth } from "@/stores/authStore";
import { ApiError } from "@/lib/apiClient";
import { UserRole, type Template } from "@/lib/types";
import { EmptyState } from "@/components/common/feedback/EmptyState";

interface FileRow {
  path: string;
  content: string;
}

const NEW_TEMPLATE_FILES: FileRow[] = [{ path: "CLAUDE.md", content: "" }];

/** Создание и редактирование шаблона: файлы и MCP-серверы. */
export function TemplateForm({
  template,
  onSaved,
  onCancel,
}: {
  template?: Template;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { user } = useAuth();
  const isAdmin = user?.role === UserRole.ADMIN;
  // GET /mcp-servers admin-only — для не-admin список серверов недоступен
  // (реальное расхождение прав доступа между api/templates.py и
  // api/mcp_servers.py, см. итоговый отчёт по Этапу 13).
  const { data: mcpServers } = useMcpServers({ enabled: isAdmin });
  const createTemplate = useCreateTemplate();
  const updateTemplate = useUpdateTemplate(template?.id ?? "");

  const [name, setName] = useState(template?.name ?? "");
  const [files, setFiles] = useState<FileRow[]>(
    template
      ? Object.entries(template.files).map(([path, content]) => ({ path, content }))
      : NEW_TEMPLATE_FILES,
  );
  const [mcpServerIds, setMcpServerIds] = useState<string[]>(template?.mcp_server_ids ?? []);

  function updateFile(index: number, patch: Partial<FileRow>) {
    setFiles((prev) => prev.map((file, i) => (i === index ? { ...file, ...patch } : file)));
  }

  function handleSave() {
    const filesRecord = Object.fromEntries(
      files.filter((file) => file.path.trim()).map((file) => [file.path, file.content]),
    );
    const onError = (error: unknown) =>
      toast.error(error instanceof ApiError ? error.message : "Не удалось сохранить шаблон");
    // Не-admin не видит серверы: пустой список стёр бы привязки, поэтому он не отправляется.
    const mcp = isAdmin ? { mcp_server_ids: mcpServerIds } : {};
    if (template) {
      updateTemplate.mutate({ name, files: filesRecord, ...mcp }, { onSuccess: onSaved, onError });
    } else {
      createTemplate.mutate({ name, files: filesRecord, ...mcp }, { onSuccess: onSaved, onError });
    }
  }

  const isPending = createTemplate.isPending || updateTemplate.isPending;

  return (
    <>
      <div className="flex flex-col gap-3">
        <div>
          <Label htmlFor="tpl-name">Название</Label>
          <Input id="tpl-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        <Card>
          <CardTitle>Файлы шаблона</CardTitle>
          <div className="flex flex-col gap-2">
            {files.length === 0 && (
              <EmptyState
                compact
                title="Файлов в шаблоне нет"
                hint="Нажмите «+ Файл» и укажите путь (например, CLAUDE.md) и содержимое — файл попадёт в репозиторий задачи."
              />
            )}
            {files.map((file, index) => (
              <div key={index} className="flex flex-col gap-1 rounded-md border border-border p-2">
                <div className="flex items-center gap-2">
                  <Input
                    aria-label="Путь файла"
                    placeholder=".claude/settings.json"
                    value={file.path}
                    onChange={(e) => updateFile(index, { path: e.target.value })}
                  />
                  <button
                    type="button"
                    aria-label={`Убрать файл ${file.path || "без пути"}`}
                    onClick={() => setFiles((prev) => prev.filter((_, i) => i !== index))}
                    className="touch-target flex items-center justify-center text-text-3 hover:text-danger"
                  >
                    <Trash2 className="size-4" />
                  </button>
                </div>
                <Textarea
                  rows={3}
                  aria-label="Содержимое файла"
                  placeholder="Содержимое файла"
                  value={file.content}
                  onChange={(e) => updateFile(index, { content: e.target.value })}
                />
              </div>
            ))}
          </div>
          <Button
            size="sm"
            variant="secondary"
            className="mt-2"
            onClick={() => setFiles((prev) => [...prev, { path: "", content: "" }])}
          >
            <Plus className="size-4" /> Файл
          </Button>
        </Card>

        <Card>
          <CardTitle>MCP-серверы шаблона</CardTitle>
          {isAdmin ? (
            <div className="flex flex-col gap-1.5">
              {(mcpServers ?? []).map((server) => (
                <label key={server.id} className="flex items-center gap-2 text-body">
                  <Checkbox
                    checked={mcpServerIds.includes(server.id)}
                    onCheckedChange={(checked) =>
                      setMcpServerIds((prev) =>
                        checked === true
                          ? [...prev, server.id]
                          : prev.filter((id) => id !== server.id),
                      )
                    }
                  />
                  {server.name}
                </label>
              ))}
              {(mcpServers ?? []).length === 0 && (
                <EmptyState
                  compact
                  title="MCP-серверов пока нет"
                  hint="Подключите сервер в «Администрирование → MCP-серверы» кнопкой «+ Сервер», затем отметьте его здесь."
                />
              )}
            </div>
          ) : (
            <div className="text-small text-text-3">
              Выбор MCP-серверов требует роли admin (см. /mcp-servers)
            </div>
          )}
        </Card>
      </div>
      <DialogFooter>
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button onClick={handleSave} disabled={!name || isPending}>
          {template ? "Сохранить" : "Создать"}
        </Button>
      </DialogFooter>
    </>
  );
}
