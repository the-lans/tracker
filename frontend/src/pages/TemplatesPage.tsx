import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useCreateTemplate, useDeleteTemplate, useTemplates } from "@/hooks/useTemplates";
import { useMcpServers } from "@/hooks/useMcpServers";
import { useAuth } from "@/stores/authStore";
import { ApiError } from "@/lib/apiClient";
import { UserRole } from "@/lib/types";

interface FileRow {
  path: string;
  content: string;
}

export function TemplatesPage() {
  const { user } = useAuth();
  const { data: templates, isLoading } = useTemplates();
  // GET /mcp-servers admin-only — для не-admin список серверов недоступен
  // (реальное расхождение прав доступа между api/templates.py и
  // api/mcp_servers.py, см. итоговый отчёт по Этапу 13).
  const { data: mcpServers } = useMcpServers({ enabled: user?.role === UserRole.ADMIN });
  const createTemplate = useCreateTemplate();
  const deleteTemplate = useDeleteTemplate();

  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [files, setFiles] = useState<FileRow[]>([{ path: "CLAUDE.md", content: "" }]);
  const [mcpServerIds, setMcpServerIds] = useState<string[]>([]);

  function updateFile(index: number, patch: Partial<FileRow>) {
    setFiles((prev) => prev.map((file, i) => (i === index ? { ...file, ...patch } : file)));
  }

  function handleCreate() {
    const filesRecord = Object.fromEntries(
      files.filter((file) => file.path.trim()).map((file) => [file.path, file.content]),
    );
    createTemplate.mutate(
      { name, files: filesRecord, mcp_server_ids: mcpServerIds },
      {
        onSuccess: () => {
          setOpen(false);
          setName("");
          setFiles([{ path: "CLAUDE.md", content: "" }]);
          setMcpServerIds([]);
        },
        onError: (error) => {
          toast.error(error instanceof ApiError ? error.message : "Не удалось создать шаблон");
        },
      },
    );
  }

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Шаблоны"
        actions={
          <Button onClick={() => setOpen(true)}>
            <Plus className="size-4" /> Шаблон
          </Button>
        }
      />
      <div className="min-h-0 flex-1 overflow-auto px-5 pb-8 lg:px-8">
        {isLoading && <div className="text-text-3">Загрузка…</div>}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(templates ?? []).map((template) => (
            <Card key={template.id} className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <div className="font-bold">{template.name}</div>
                <button
                  type="button"
                  onClick={() =>
                    deleteTemplate.mutate(template.id, {
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
              </div>
              <div className="text-[12px] text-text-3">
                {Object.keys(template.files).length} файл(ов)
              </div>
            </Card>
          ))}
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Новый шаблон</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div>
              <Label htmlFor="tpl-name">Название</Label>
              <Input id="tpl-name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>

            <Card>
              <CardTitle>Файлы шаблона</CardTitle>
              <div className="flex flex-col gap-2">
                {files.map((file, index) => (
                  <div key={index} className="flex flex-col gap-1 rounded-md border border-border p-2">
                    <div className="flex items-center gap-2">
                      <Input
                        placeholder=".claude/settings.json"
                        value={file.path}
                        onChange={(e) => updateFile(index, { path: e.target.value })}
                      />
                      <button
                        type="button"
                        onClick={() => setFiles((prev) => prev.filter((_, i) => i !== index))}
                        className="touch-target flex items-center justify-center text-text-3 hover:text-danger"
                      >
                        <Trash2 className="size-4" />
                      </button>
                    </div>
                    <Textarea
                      rows={3}
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
              {user?.role === UserRole.ADMIN ? (
                <div className="flex flex-col gap-1.5">
                  {(mcpServers ?? []).map((server) => (
                    <label key={server.id} className="flex items-center gap-2 text-[13px]">
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
                    <div className="text-[12px] text-text-3">Нет зарегистрированных MCP-серверов</div>
                  )}
                </div>
              ) : (
                <div className="text-[12px] text-text-3">
                  Выбор MCP-серверов требует роли admin (см. /mcp-servers)
                </div>
              )}
            </Card>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Отмена
            </Button>
            <Button onClick={handleCreate} disabled={!name || createTemplate.isPending}>
              Создать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
