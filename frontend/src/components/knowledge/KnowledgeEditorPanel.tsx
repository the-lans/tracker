import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { AgentMessageText } from "@/components/tasks/AgentMessageText";
import { KnowledgeHistory } from "@/components/knowledge/KnowledgeHistory";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Download, FilePlus2, FolderPlus, RefreshCw, Upload } from "lucide-react";
import { ConfirmDialog } from "@/components/common/dialogs/ConfirmDialog";
import type { useKnowledgeEditor } from "@/hooks/useKnowledgeEditor";
import type { KnowledgeActions } from "@/hooks/useKnowledgeActions";
import type { KnowledgeEntry, KnowledgeSection, KnowledgeVersion } from "@/lib/knowledge.types";

type Editor = ReturnType<typeof useKnowledgeEditor>;

export function KnowledgeEditorPanel({editor, actions, section, sections, versions, admin, writable, folder, trash, mapEntry, guard, onRemove, onOpen, onDirectoryRemoved, onShowDeletedMap}: {
  editor: Editor;
  actions: KnowledgeActions;
  section: KnowledgeSection;
  sections: KnowledgeSection[];
  versions: KnowledgeVersion[];
  admin: boolean;
  writable: boolean;
  folder: string;
  trash: boolean;
  mapEntry: KnowledgeEntry | null | undefined;
  guard: (action: () => void) => void;
  onRemove: () => void;
  onOpen: (entry: KnowledgeEntry, version?: number) => void;
  onDirectoryRemoved: (path: string) => void;
  onShowDeletedMap: () => void;
}) {
  const [preview, setPreview] = useState(false);
  const [destination, setDestination] = useState("");
  const [destinationSection, setDestinationSection] = useState("");
  const [confirmTrash, setConfirmTrash] = useState(false);
  const entry = editor.entry;
  const busy = editor.loading || actions.pending;
  const readOnly = busy || editor.binary || !writable || Boolean(entry?.deleted_at);
  const selectedDirectory = Boolean(entry?.is_directory);
  const creatingDirectory = !entry && editor.directory;

  function startNew(directory: boolean) {
    guard(() => { editor.reset(); editor.setDirectory(directory); editor.setPath(folder ? `${folder}/` : ""); setPreview(false); });
  }

  async function changeDeleted() {
    if (!entry) return;
    if (await actions.trash() && entry.is_directory && !entry.deleted_at) onDirectoryRemoved(entry.path);
  }

  async function moveEntry() {
    if (!entry) return;
    if (await actions.move(destinationSection || section.id, destination) && entry.is_directory) onDirectoryRemoved(entry.path);
  }

  return <>
    {section.publication_pending && <p role="status" className="rounded-md bg-surface-2 p-3 text-sm text-text-2">Файл сохранён. Обновление файлов агента ожидает синхронизации.</p>}
    {admin && <div className="rounded-lg border border-border bg-surface-2 p-3 sm:p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" title="Синхронизировать хранилище" disabled={actions.pending} onClick={() => { void actions.synchronize(); }}><RefreshCw /> Синхронизировать</Button>
        <Button variant="danger" disabled={actions.pending} onClick={onRemove}>Удалить раздел</Button>
      </div>
      <p className="mt-2 text-sm text-text-3">Синхронизация обновляет файлы для агентов и очищает неиспользуемые данные хранилища.</p>
      <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
        <label className="flex min-h-10 cursor-pointer items-center gap-3 text-sm text-text-2"><Checkbox disabled={actions.pending} checked={section.user_read}
          onCheckedChange={(checked) => { const value = checked === true; void actions.setPermissions(section, value, value && section.user_write); }} /> Пользователи: чтение</label>
        <label className="flex min-h-10 cursor-pointer items-center gap-3 text-sm text-text-2"><Checkbox disabled={actions.pending} checked={section.user_write}
          onCheckedChange={(checked) => { const value = checked === true; void actions.setPermissions(section, section.user_read || value, value); }} /> Пользователи: запись</label>
      </div>
    </div>}
    <p className="text-sm text-text-3">{writable ? "Чтение и запись" : "Только чтение"}</p>
    <p className="break-all text-sm text-text-2">Папка: {folder || "Корень раздела"}</p>
    {trash && <p className="rounded-md bg-surface-2 p-3 text-sm text-text-2">Корзина: выберите удалённый файл или папку для восстановления.</p>}
    {writable && !trash && <>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" onClick={() => startNew(false)}><FilePlus2 /> Новый файл</Button>
        <Button variant="secondary" onClick={() => startNew(true)}><FolderPlus /> Новая папка</Button>
        <Button asChild variant="secondary" className="cursor-pointer has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50">
          <label><Upload /> Загрузить файл<input className="sr-only" type="file" disabled={actions.pending} onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void actions.upload(file, folder);
            event.target.value = "";
          }} /></label>
        </Button>
        {mapEntry === null && <Button variant="secondary" title="Создать README.md со ссылками и описанием ресурсов" disabled={actions.pending} onClick={() => { void actions.createMap(); }}>Создать карту ресурсов</Button>}
        {mapEntry?.deleted_at && <Button variant="secondary" onClick={onShowDeletedMap}>Найти README.md в корзине</Button>}
      </div>
    </>}
    {selectedDirectory && <p className="text-sm text-text-2">{entry?.deleted_at ? "Удалённая папка" : "Выбрана папка"}: {entry?.path}</p>}
    {(!selectedDirectory && !trash) && <>
    {creatingDirectory && <p className="text-sm text-text-2">Укажите путь новой папки относительно корня раздела.</p>}
    <Input aria-label="Путь файла" placeholder="Документы/Карта.md" value={editor.path}
      disabled={busy || Boolean(entry) || !writable} onChange={(event) => editor.setPath(event.target.value)} />
    {!creatingDirectory && <>
    {editor.viewedVersion !== null && <p role="status" className="rounded-md bg-surface-2 p-3 text-sm text-text-2">Открыта версия {editor.viewedVersion}. Сохранение создаст новую версию файла.</p>}
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="secondary" aria-pressed={preview} onClick={() => setPreview(!preview)}>{preview ? "Редактор" : "Предпросмотр"}</Button>
      {entry && <>
        <Button variant="secondary" onClick={() => guard(() => onOpen(entry))}><RefreshCw /> Перечитать файл</Button>
        <Button variant="secondary" onClick={() => { void actions.download(); }}><Download /> Скачать</Button>
      </>}
    </div>
    {preview ? <div className="min-h-40 min-w-0 overflow-auto rounded-md border border-border bg-surface p-4"><AgentMessageText text={editor.text} /></div> : <Textarea aria-label="Содержимое файла"
      className="min-h-80 flex-1 font-mono" value={editor.text} disabled={readOnly}
      onChange={(event) => editor.setText(event.target.value)} />}
    </>}
    </>}
    {writable && <div className="flex flex-wrap gap-2">
      {!selectedDirectory && !trash && <Button disabled={readOnly || !editor.path} onClick={() => { void actions.save(); }}>{creatingDirectory ? "Создать папку" : "Сохранить"}</Button>}
      {entry && <Button variant="secondary" disabled={busy} onClick={() => { if (entry.is_directory && !entry.deleted_at) setConfirmTrash(true); else void changeDeleted(); }}>{entry.deleted_at ? "Восстановить" : "В корзину"}</Button>}
    </div>}
    {entry && !trash && <>
      {writable && <details className="rounded-lg border border-border bg-surface p-3">
        <summary className="cursor-pointer font-bold text-text-2 hover:text-text">Переименовать или перенести</summary>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
          <Input className="min-w-0 flex-1" aria-label="Новый путь" placeholder="Новый путь" value={destination} onChange={(event) => setDestination(event.target.value)} />
          <Select value={destinationSection || section.id} onValueChange={setDestinationSection}>
            <SelectTrigger aria-label="Целевой раздел" className="sm:w-56 sm:shrink-0"><SelectValue /></SelectTrigger>
            <SelectContent>{sections.filter((item) => admin || item.user_write).map((item) => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent>
          </Select>
          <Button className="shrink-0 self-start" disabled={busy || !destination} onClick={() => { void moveEntry(); }}>Перенести</Button>
        </div>
      </details>}
      {!selectedDirectory && <KnowledgeHistory versions={versions} currentVersion={entry.version} disabled={busy} onOpen={(version) => guard(() => onOpen(entry, version))} />}
    </>}
    <ConfirmDialog open={confirmTrash} onOpenChange={setConfirmTrash} title="Переместить папку в корзину?" description="Папка и её содержимое будут перемещены в корзину." confirmLabel="В корзину" danger pending={busy} onConfirm={() => { setConfirmTrash(false); void changeDeleted(); }} />
  </>;
}
