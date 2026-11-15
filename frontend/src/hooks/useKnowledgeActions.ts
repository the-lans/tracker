import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { errorMessage } from "@/lib/errors";
import type { KnowledgeEntry, KnowledgeSection } from "@/lib/knowledge.types";
import type { useKnowledgeEditor } from "@/hooks/useKnowledgeEditor";

const MAP_TEMPLATE = "# Карта ресурсов\n\n## Документация\nДобавьте ссылки на источники и название MCP-подключения.\n\n## Репозитории\nДобавьте ссылки и назначение проектов.\n\n## Правила поиска\nУкажите, где проверять актуальность информации.\n";
type Editor = ReturnType<typeof useKnowledgeEditor>;

export function useKnowledgeActions({ editor, sectionId, onError, onDirectoryCreated }: {
  editor: Editor;
  sectionId: string;
  onError: (message: string) => void;
  onDirectoryCreated: (path: string) => void;
}) {
  const cache = useQueryClient();
  const mutation = useMutation({
    mutationFn: (operation: () => Promise<unknown>) => operation(),
    onSuccess: () => { void cache.invalidateQueries({ queryKey: ["knowledge"] }); },
  });

  async function perform(operation: () => Promise<unknown>): Promise<boolean> {
    try {
      await mutation.mutateAsync(operation);
      onError("");
      return true;
    } catch (cause) {
      onError(errorMessage(cause, "Не удалось выполнить операцию"));
      return false;
    }
  }

  async function save() {
    if (editor.loading) return;
    const generation = editor.generation();
    const sentText = editor.text;
    await perform(async () => {
      const saved = await api.put<KnowledgeEntry>(`/knowledge/sections/${sectionId}/entries`, {
        path: editor.path, content: sentText, expected_version: editor.entry?.version ?? 0,
        is_directory: editor.directory,
      });
      if (!editor.entry && saved.is_directory && editor.generation() === generation) onDirectoryCreated(saved.path);
      editor.acceptSaved(saved, sentText, generation);
    });
  }

  async function trash() {
    const entry = editor.entry;
    if (!entry) return false;
    const generation = editor.generation();
    return perform(async () => {
      await api.patch(`/knowledge/entries/${entry.id}/deleted`, {
        expected_version: entry.version, deleted: !entry.deleted_at,
      });
      editor.resetIfCurrent(generation);
    });
  }

  async function move(destinationSection: string, path: string) {
    const entry = editor.entry;
    if (!entry) return false;
    const generation = editor.generation();
    return perform(async () => {
      await api.patch(`/knowledge/entries/${entry.id}/location`, {
        section_id: destinationSection, path, expected_version: entry.version,
      });
      editor.resetIfCurrent(generation);
    });
  }

  async function upload(file: File, directory = "") {
    const body = new FormData();
    body.append("file", file);
    const path = directory ? `${directory}/${file.name}` : file.name;
    await perform(() => api.post(`/knowledge/sections/${sectionId}/upload?path=${encodeURIComponent(path)}`, body));
  }

  async function download() {
    const entry = editor.entry;
    if (!entry) return;
    try {
      const blob = await api.getBlob(`/knowledge/entries/${entry.id}/download`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = entry.path.split("/").pop()!;
      link.click();
      URL.revokeObjectURL(url);
    } catch (cause) {
      onError(errorMessage(cause, "Не удалось скачать файл"));
    }
  }

  return {
    pending: mutation.isPending,
    save, trash, move, upload, download,
    createSection: (name: string) => perform(() => api.post("/knowledge/sections", {
      name, user_read: true, user_write: false,
    })),
    setPermissions: (section: KnowledgeSection, read: boolean, write: boolean) => perform(() =>
      api.patch(`/knowledge/sections/${section.id}`, {name: section.name, user_read: read, user_write: write})),
    removeSection: () => perform(() => api.delete(`/knowledge/sections/${sectionId}`)),
    synchronize: () => perform(() => api.post("/knowledge/maintenance")),
    createMap: () => perform(() => api.put(`/knowledge/sections/${sectionId}/entries`, {
      path: "README.md", content: MAP_TEMPLATE, expected_version: 0,
    })),
  };
}

export type KnowledgeActions = ReturnType<typeof useKnowledgeActions>;
