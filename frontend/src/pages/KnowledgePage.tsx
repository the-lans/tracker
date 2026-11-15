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
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export function KnowledgePage() {
  const admin = useIsAdmin();
  const cache = useQueryClient();
  const editor = useKnowledgeEditor();
  const [sectionId, setSectionId] = useState("");
  const [folder, setFolder] = useState("");
  const [sectionName, setSectionName] = useState("");
  const [filter, setFilter] = useState("");
  const [trash, setTrash] = useState(false);
  const [showFiles, setShowFiles] = useState(true);
  const [notice, setNotice] = useState("");
  const [removeSection, setRemoveSection] = useState(false);
  const actions = useKnowledgeActions({editor, sectionId, onError: setNotice, onDirectoryCreated: setFolder});
  const changes = useUnsavedChangesGuard(editor.text !== editor.originalText);
  const guard = changes.guard;

  const sections = useQuery({queryKey: ["knowledge", "sections"], queryFn: () => api.get<KnowledgeSection[]>("/knowledge/sections")});
  const entries = useQuery({
    queryKey: ["knowledge", sectionId, "entries"], enabled: Boolean(sectionId),
    queryFn: () => api.get<KnowledgeEntry[]>(`/knowledge/sections/${sectionId}/entries`),
  });
  const searching = filter.trim().length >= 2 && !trash;
  const search = useQuery({
    queryKey: ["knowledge", sectionId, "search", filter], enabled: Boolean(sectionId) && searching,
    queryFn: () => api.get<KnowledgeEntry[]>(`/knowledge/sections/${sectionId}/search`, {query: filter}),
  });
  const files = searching ? search : entries;
  const mapEntry = entries.data?.find((file) => file.path === "README.md");
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
    if (await actions.removeSection()) { setSectionId(""); setFolder(""); editor.reset(); }
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
    <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-auto px-4 pb-8 pt-4 lg:flex-row lg:items-start lg:px-6">
      <aside className="flex min-w-0 shrink-0 flex-col gap-4 lg:w-72">
        <p className="text-sm text-text-3">Раздел объединяет файлы с общими правами доступа. Агенты задач могут обращаться к разрешённым разделам.</p>
        {admin && <div className="flex gap-2">
          <Input className="min-w-0 flex-1" aria-label="Название раздела" placeholder="Название раздела" value={sectionName} onChange={(event) => setSectionName(event.target.value)} />
          <Button className="shrink-0" disabled={!sectionName.trim() || actions.pending} onClick={() => {
            void actions.createSection(sectionName).then((created) => { if (created) setSectionName(""); });
          }}>Создать</Button>
        </div>}
        <div className="space-y-1.5">
          <label htmlFor="knowledge-section" className="text-sm font-bold text-text-2">Раздел</label>
          <Select value={sectionId} onValueChange={(next) => guard(() => { setSectionId(next); setFolder(""); setTrash(false); editor.reset(); })}>
            <SelectTrigger id="knowledge-section"><SelectValue placeholder="Выберите раздел" /></SelectTrigger>
            <SelectContent>{sections.data?.map((item) => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <SearchInput aria-label="Поиск файлов" placeholder="Поиск по названию и содержимому" value={filter}
          onChange={(event) => setFilter(event.target.value)} onClear={() => setFilter("")} />
        <label className="flex min-h-10 cursor-pointer items-center gap-3 px-0.5 text-sm text-text-2">
          <Checkbox checked={trash} onCheckedChange={(checked) => guard(() => { setTrash(checked === true); setFolder(""); editor.reset(); })} /> Корзина
        </label>
        {section && <Button variant="ghost" className="self-start" onClick={() => guard(() => { setFolder(""); editor.reset(); })}>Корень раздела</Button>}
        {section && <Button variant="secondary" className="self-start lg:hidden" aria-expanded={showFiles} onClick={() => setShowFiles(!showFiles)}>{showFiles ? "Скрыть файлы" : "Показать файлы"}</Button>}
        <div className={showFiles ? "block" : "hidden lg:block"}>
        <KnowledgeTree entries={files.data?.filter((file) => Boolean(file.deleted_at) === trash) ?? []}
          selectedPath={editor.entry?.path ?? folder}
          onFolder={(path, entry) => guard(() => { setFolder(path); if (entry) editor.selectDirectory(entry); else editor.reset(); })}
          onOpen={(file) => guard(() => { setFolder(file.path.split("/").slice(0, -1).join("/")); setShowFiles(false); void open(file); })} />
        {section && !files.isLoading && !files.error && !files.data?.some((file) => Boolean(file.deleted_at) === trash) && <p className="text-sm text-text-3">{trash ? "Корзина пуста." : searching ? "Ничего не найдено." : "В разделе пока нет файлов."}</p>}
        </div>
      </aside>
      <main className="flex min-w-0 flex-1 flex-col gap-3">
        {(sections.error || entries.error || files.error) && <p role="alert" className="text-danger">{errorMessage(sections.error || entries.error || files.error, "Не удалось прочитать базу знаний")}</p>}
        {notice && <p role="alert">{notice}</p>}
        {editor.error && <p role="alert">{editor.error}</p>}
        {editor.loading && <p role="status">Загрузка файла…</p>}
        {!section && !sections.error && <p className="rounded-lg border border-border bg-surface-2 p-4 text-sm text-text-3">Выберите раздел, чтобы открыть файлы базы знаний.</p>}
        {section && <KnowledgeEditorPanel key={sectionId} editor={editor} actions={actions} section={section}
          sections={sections.data ?? []} versions={history.data ?? []} admin={admin}
          writable={admin || section.user_write} folder={folder} trash={trash} mapEntry={entries.isSuccess ? mapEntry ?? null : undefined} guard={guard} onRemove={() => setRemoveSection(true)} onOpen={(file, version) => { void open(file, version); }}
          onShowDeletedMap={() => guard(() => { if (!mapEntry) return; setTrash(true); setFolder(""); setShowFiles(true); if (mapEntry.is_directory) editor.selectDirectory(mapEntry); else void open(mapEntry); })}
          onDirectoryRemoved={(path) => setFolder((current) => current === path ? path.split("/").slice(0, -1).join("/") : current)} />}
      </main>
    </div>
  </div>;
}
