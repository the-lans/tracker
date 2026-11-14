import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { AgentMessageText } from "@/components/tasks/AgentMessageText";
import { KnowledgeHistory } from "@/components/knowledge/KnowledgeHistory";
import type { useKnowledgeEditor } from "@/hooks/useKnowledgeEditor";
import type { KnowledgeActions } from "@/hooks/useKnowledgeActions";
import type { KnowledgeEntry, KnowledgeSection, KnowledgeVersion } from "@/lib/knowledge.types";

type Editor = ReturnType<typeof useKnowledgeEditor>;

export function KnowledgeEditorPanel({editor, actions, section, sections, versions, admin, writable, hasMap, guard, onRemove, onOpen}: {
  editor: Editor;
  actions: KnowledgeActions;
  section: KnowledgeSection;
  sections: KnowledgeSection[];
  versions: KnowledgeVersion[];
  admin: boolean;
  writable: boolean;
  hasMap: boolean;
  guard: (action: () => void) => void;
  onRemove: () => void;
  onOpen: (entry: KnowledgeEntry, version?: number) => void;
}) {
  const [preview, setPreview] = useState(false);
  const [destination, setDestination] = useState("");
  const [destinationSection, setDestinationSection] = useState("");
  const entry = editor.entry;
  const busy = editor.loading || actions.pending;
  const readOnly = busy || editor.binary || !writable || Boolean(entry?.deleted_at);

  return <>
    {section.publication_pending && <p role="status">Файл сохранён. Обновление файлов агента ожидает синхронизации.</p>}
    {admin && <>
      <Button disabled={actions.pending} onClick={() => { void actions.synchronize(); }}>Синхронизировать хранилище</Button>
      <Button disabled={actions.pending} variant="danger" onClick={onRemove}>Удалить раздел</Button>
      <div className="flex flex-wrap gap-3">
        <label><input type="checkbox" disabled={actions.pending} checked={section.user_read}
          onChange={(event) => { void actions.setPermissions(section, event.target.checked, event.target.checked && section.user_write); }} /> Пользователи: чтение</label>
        <label><input type="checkbox" disabled={actions.pending} checked={section.user_write}
          onChange={(event) => { void actions.setPermissions(section, section.user_read || event.target.checked, event.target.checked); }} /> Пользователи: запись</label>
      </div>
    </>}
    <p>{writable ? "Чтение и запись" : "Только чтение"}</p>
    {writable && <>
      {!hasMap && <Button disabled={actions.pending} onClick={() => { void actions.createMap(); }}>Создать карту ресурсов</Button>}
      <Button onClick={() => guard(editor.reset)}>Новый файл</Button>
      {!entry && <label><input type="checkbox" checked={editor.directory} disabled={busy}
        onChange={(event) => editor.setDirectory(event.target.checked)} /> Папка</label>}
      <label>Загрузить файл<input type="file" disabled={actions.pending} onChange={(event) => {
        const file = event.target.files?.[0];
        if (file) void actions.upload(file);
      }} /></label>
    </>}
    <Input aria-label="Путь файла" placeholder="Документы/Карта.md" value={editor.path}
      disabled={busy || Boolean(entry) || !writable} onChange={(event) => editor.setPath(event.target.value)} />
    <Button onClick={() => setPreview(!preview)}>{preview ? "Редактор" : "Предпросмотр"}</Button>
    {preview ? <AgentMessageText text={editor.text} /> : <Textarea aria-label="Содержимое файла"
      className="min-h-80 flex-1 font-mono" value={editor.text} disabled={readOnly}
      onChange={(event) => editor.setText(event.target.value)} />}
    {writable && <div className="flex flex-wrap gap-2">
      <Button disabled={readOnly || !editor.path} onClick={() => { void actions.save(); }}>Сохранить</Button>
      {entry && <Button disabled={busy} onClick={() => { void actions.trash(); }}>{entry.deleted_at ? "Восстановить" : "В корзину"}</Button>}
    </div>}
    {entry && <>
      <Button onClick={() => guard(() => onOpen(entry))}>Перечитать файл</Button>
      {writable && <details>
        <summary>Переименовать или перенести</summary>
        <Input aria-label="Новый путь" value={destination} onChange={(event) => setDestination(event.target.value)} />
        <select aria-label="Целевой раздел" value={destinationSection || section.id}
          onChange={(event) => setDestinationSection(event.target.value)}>
          {sections.filter((item) => admin || item.user_write).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        <Button disabled={busy || !destination} onClick={() => { void actions.move(destinationSection || section.id, destination); }}>Перенести</Button>
      </details>}
      <Button onClick={() => { void actions.download(); }}>Скачать</Button>
      <KnowledgeHistory versions={versions} disabled={busy} onOpen={(version) => guard(() => onOpen(entry, version))} />
    </>}
  </>;
}
