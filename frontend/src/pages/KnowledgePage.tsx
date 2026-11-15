import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { errorMessage } from "@/lib/errors";
import { PageHeader } from "@/components/layout/PageHeader";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/common/dialogs/ConfirmDialog";
import { KnowledgeTree } from "@/components/knowledge/KnowledgeTree";
import { KnowledgeEditorPanel } from "@/components/knowledge/KnowledgeEditorPanel";
import { useKnowledgeEditor } from "@/hooks/useKnowledgeEditor";
import { useKnowledgeActions } from "@/hooks/useKnowledgeActions";
import { useUnsavedChangesGuard } from "@/hooks/useUnsavedChangesGuard";
import { useIsAdmin } from "@/hooks/useIsAdmin";
import type { KnowledgeEntry, KnowledgeSection, KnowledgeVersion } from "@/lib/knowledge.types";
import { SearchInput } from "@/components/common/inputs/SearchInput";

export function KnowledgePage() {
  const admin = useIsAdmin();
  const cache = useQueryClient();
  const editor = useKnowledgeEditor();
  const [sectionId, setSectionId] = useState("");
  const [sectionName, setSectionName] = useState("");
  const [filter, setFilter] = useState("");
  const [trash, setTrash] = useState(false);
  const [notice, setNotice] = useState("");
  const [removeSection, setRemoveSection] = useState(false);
  const actions = useKnowledgeActions({editor, sectionId, onError: setNotice});
  const changes = useUnsavedChangesGuard(editor.text !== editor.originalText);
  const guard = changes.guard;

  const sections = useQuery({queryKey: ["knowledge", "sections"], queryFn: () => api.get<KnowledgeSection[]>("/knowledge/sections")});
  const files = useQuery({
    queryKey: ["knowledge", sectionId, filter, trash], enabled: Boolean(sectionId),
    queryFn: () => filter.trim().length >= 2 && !trash
      ? api.get<KnowledgeEntry[]>(`/knowledge/sections/${sectionId}/search`, {query: filter})
      : api.get<KnowledgeEntry[]>(`/knowledge/sections/${sectionId}/entries`),
  });
  const history = useQuery({
    queryKey: ["knowledge", "history", editor.entry?.id], enabled: Boolean(editor.entry),
    queryFn: () => api.get<KnowledgeVersion[]>(`/knowledge/entries/${editor.entry!.id}/history`),
  });
  const section = sections.data?.find((item) => item.id === sectionId);

  async function open(file: KnowledgeEntry, version?: number) {
    if (await editor.open(file, version)) {
      setNotice("");
      void cache.invalidateQueries({queryKey: ["knowledge"]});
    }
  }

  async function confirmRemoval() {
    if (await actions.removeSection()) { setSectionId(""); editor.reset(); }
    setRemoveSection(false);
  }

  return <div className="flex h-full min-h-0 flex-col">
    <PageHeader title="База знаний" />
    <ConfirmDialog open={removeSection} onOpenChange={setRemoveSection} title="Удалить раздел базы знаний?"
      description="Файлы и история раздела будут удалены. Действие доступно только администратору."
      confirmLabel="Удалить раздел" danger pending={actions.pending} onConfirm={() => { void confirmRemoval(); }} />
    <ConfirmDialog open={changes.pending} onOpenChange={(openDialog) => { if (!openDialog) changes.cancel(); }}
      title="Есть несохранённые изменения" description="Продолжить и отменить изменения файла?" confirmLabel="Продолжить"
      onConfirm={changes.confirm} />
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto p-4 lg:flex-row">
      <aside className="flex shrink-0 flex-col gap-3 lg:w-72">
        {admin && <div className="flex gap-2">
          <Input aria-label="Название раздела" value={sectionName} onChange={(event) => setSectionName(event.target.value)} />
          <Button disabled={!sectionName.trim() || actions.pending} onClick={() => {
            void actions.createSection(sectionName).then((created) => { if (created) setSectionName(""); });
          }}>Создать</Button>
        </div>}
        <label>Раздел<select className="block w-full rounded border bg-surface p-2" value={sectionId}
          onChange={(event) => { const next = event.target.value; guard(() => { setSectionId(next); editor.reset(); }); }}>
          <option value="">Выберите раздел</option>
          {sections.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        <SearchInput aria-label="Поиск файлов" placeholder="Поиск по названию и содержимому" value={filter}
          onChange={(event) => setFilter(event.target.value)} onClear={() => setFilter("")} />
        <label><input type="checkbox" checked={trash} onChange={(event) => setTrash(event.target.checked)} /> Корзина</label>
        <KnowledgeTree entries={files.data?.filter((file) => Boolean(file.deleted_at) === trash) ?? []}
          onOpen={(file) => guard(() => { void open(file); })} />
      </aside>
      <main className="flex min-w-0 flex-1 flex-col gap-3">
        {(sections.error || files.error) && <p role="alert" className="text-danger">{errorMessage(sections.error || files.error, "Не удалось прочитать базу знаний")}</p>}
        {notice && <p role="alert">{notice}</p>}
        {editor.error && <p role="alert">{editor.error}</p>}
        {editor.loading && <p role="status">Загрузка файла…</p>}
        {section && <KnowledgeEditorPanel key={sectionId} editor={editor} actions={actions} section={section}
          sections={sections.data ?? []} versions={history.data ?? []} admin={admin}
          writable={admin || section.user_write} hasMap={files.data?.some((file) => file.path === "README.md") ?? false} guard={guard} onRemove={() => setRemoveSection(true)} onOpen={(file, version) => { void open(file, version); }} />}
      </main>
    </div>
  </div>;
}
