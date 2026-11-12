import { useState } from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { DialogFooter } from "@/components/ui/dialog";
import { useCreateTemplate, useUpdateTemplate } from "@/hooks/useTemplates";
import { useMcpServers } from "@/hooks/useMcpServers";
import { errorMessage } from "@/lib/errors";
import { duplicatePathMessage, duplicateTemplatePaths } from "@/lib/templateFiles";
import type { Template } from "@/lib/types";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { TemplateFileField } from "@/components/templates/TemplateFileField";
import type { TemplateFileRow } from "@/components/templates/templateForm.types";

let nextRowKey = 0;

// Раздел 15.1: новый файл шаблона по умолчанию загружается с диска.
function fileRow(path: string, content: string, fromFile = true): TemplateFileRow {
  nextRowKey += 1;
  return { key: nextRowKey, path, content, fromFile };
}

function savedFileRows(template: Template): TemplateFileRow[] {
  const uploaded = new Set(template.uploaded_file_paths);
  return Object.entries(template.files).map(([path, content]) =>
    fileRow(path, content, uploaded.has(path)),
  );
}

const NEW_TEMPLATE_FILE_PATH = "CLAUDE.md";

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
  // Раздел 10.5, 19.2: список серверов читает любой пользователь, меняет — только admin.
  const { data: mcpServers } = useMcpServers();
  const createTemplate = useCreateTemplate();
  const updateTemplate = useUpdateTemplate(template?.id ?? "");

  const [name, setName] = useState(template?.name ?? "");
  const [files, setFiles] = useState<TemplateFileRow[]>(() =>
    template ? savedFileRows(template) : [fileRow(NEW_TEMPLATE_FILE_PATH, "")],
  );
  const [mcpServerIds, setMcpServerIds] = useState<string[]>(template?.mcp_server_ids ?? []);

  function updateFile(index: number, patch: Partial<TemplateFileRow>) {
    setFiles((prev) => prev.map((file, i) => (i === index ? { ...file, ...patch } : file)));
  }

  const duplicatePaths = duplicateTemplatePaths(files.map((file) => file.path));

  function handleSave() {
    const savedRows = files
      .map((file) => ({ ...file, path: file.path.trim() }))
      .filter((file) => file.path);
    const filesRecord = Object.fromEntries(savedRows.map((file) => [file.path, file.content]));
    const uploadedFilePaths = savedRows.filter((file) => file.fromFile).map((file) => file.path);
    const onError = (error: unknown) =>
      toast.error(errorMessage(error, "Не удалось сохранить шаблон"));
    const body = {
      name,
      files: filesRecord,
      uploaded_file_paths: uploadedFilePaths,
      mcp_server_ids: mcpServerIds,
    };
    if (template) {
      updateTemplate.mutate(body, { onSuccess: onSaved, onError });
    } else {
      createTemplate.mutate(body, { onSuccess: onSaved, onError });
    }
  }

  const isPending = createTemplate.isPending || updateTemplate.isPending;

  return (
    <>
      <div className="flex flex-col gap-3">
        <div>
          <Label htmlFor="tpl-name" required>Название</Label>
          <Input id="tpl-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        <Card>
          <CardTitle>Файлы шаблона</CardTitle>
          <div className="flex flex-col gap-2">
            {files.length === 0 && (
              <EmptyState
                compact
                title="Файлов в шаблоне нет"
                hint="Нажмите «+ Файл» и укажите путь (например, CLAUDE.md) и содержимое — текстом или из файла с диска. Файл попадёт в рабочий каталог задачи, рядом с репозиториями."
              />
            )}
            {files.map((file, index) => (
              <TemplateFileField
                key={file.key}
                row={file}
                pathError={
                  duplicatePaths.has(file.path.trim()) ? duplicatePathMessage(file.path.trim()) : null
                }
                onChange={(patch) => updateFile(index, patch)}
                onRemove={() => setFiles((prev) => prev.filter((_, i) => i !== index))}
              />
            ))}
          </div>
          <Button
            size="sm"
            variant="secondary"
            className="mt-2"
            onClick={() => setFiles((prev) => [...prev, fileRow("", "")])}
          >
            <Plus className="size-4" /> Файл
          </Button>
        </Card>

        <Card>
          <CardTitle>MCP-серверы шаблона</CardTitle>
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
                hint="Серверы подключает администратор в «Администрирование → MCP-серверы». После этого отметьте нужные здесь."
              />
            )}
          </div>
        </Card>
      </div>
      <DialogFooter>
        <Button variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button onClick={handleSave} disabled={!name || isPending || duplicatePaths.size > 0}>
          {template ? "Сохранить" : "Создать"}
        </Button>
      </DialogFooter>
    </>
  );
}
