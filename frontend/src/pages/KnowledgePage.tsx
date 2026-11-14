import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { PageHeader } from "@/components/layout/PageHeader";
import { Input, Textarea } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useIsAdmin } from "@/hooks/useIsAdmin";
import { KnowledgeTree } from "@/components/knowledge/KnowledgeTree";
import { ConfirmDialog } from "@/components/common/dialogs/ConfirmDialog";
import { AgentMessageText } from "@/components/tasks/AgentMessageText";
import { errorMessage } from "@/lib/errors";

interface Section { id: string; name: string; user_read: boolean; user_write: boolean }
interface Entry { id: string; path: string; version: number; is_directory: boolean; deleted_at: string | null }

export function KnowledgePage() {
  const admin = useIsAdmin();
  const navigate = useNavigate();
  const cache = useQueryClient();
  const [sectionId, setSectionId] = useState("");
  const [sectionName, setSectionName] = useState("");
  const [entry, setEntry] = useState<Entry | null>(null);
  const [path, setPath] = useState("");
  const [text, setText] = useState("");
  const [filter, setFilter] = useState("");
  const [trash, setTrash] = useState(false);
  const [notice, setNotice] = useState("");
  const [preview, setPreview] = useState(false);
  const [binary, setBinary] = useState(false);
  const [directory, setDirectory] = useState(false);
  const [destination, setDestination] = useState("");
  const [destinationSection, setDestinationSection] = useState("");
  const [originalText, setOriginalText] = useState("");
  const [removeSection, setRemoveSection] = useState(false);
  const [pendingChange, setPendingChange] = useState<(() => void) | null>(null);
  function guard(action: () => void) {
    if (text !== originalText) setPendingChange(() => action);
    else action();
  }
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => { if (text !== originalText) { event.preventDefault(); event.returnValue = ""; } };
    const onLink = (event: MouseEvent) => {
      if (text === originalText || event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
      const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!(link instanceof HTMLAnchorElement) || link.origin !== location.origin || link.target === "_blank") return;
      event.preventDefault(); event.stopPropagation();
      setPendingChange(() => () => navigate(link.pathname + link.search + link.hash));
    };
    window.addEventListener("beforeunload", beforeUnload);
    window.addEventListener("click", onLink, true);
    return () => { window.removeEventListener("beforeunload", beforeUnload); window.removeEventListener("click", onLink, true); };
  }, [text, originalText, navigate]);
  const history = useQuery({ queryKey: ["knowledge", "history", entry?.id], enabled: Boolean(entry), queryFn: () => api.get<{version:number; created_at:string; created_by:string; task_id:string|null}[]>(`/knowledge/entries/${entry!.id}/history`) });
  const sections = useQuery({ queryKey: ["knowledge", "sections"], queryFn: () => api.get<Section[]>("/knowledge/sections") });
  const files = useQuery({ queryKey: ["knowledge", sectionId, filter, trash], enabled: Boolean(sectionId), queryFn: () => filter.trim().length >= 2 && !trash ? api.get<Entry[]>(`/knowledge/sections/${sectionId}/search`, {query:filter}) : api.get<Entry[]>(`/knowledge/sections/${sectionId}/entries`) });
  const section = sections.data?.find((s) => s.id === sectionId);
  const writable = admin || section?.user_write;
  const mutation = useMutation({
    mutationFn: async (action: "section" | "save" | "delete" | "restore" | "permissions") => {
      if (action === "permissions" && section) {
        await api.patch(`/knowledge/sections/${sectionId}`, section);
      } else if (action === "section") {
        await api.post("/knowledge/sections", { name: sectionName, user_read: true, user_write: false });
        setSectionName("");
      } else if (action === "save") {
        const saved = await api.put<Entry>(`/knowledge/sections/${sectionId}/entries`, { path, content: text, expected_version: entry?.version ?? 0, is_directory: directory });
        setEntry(saved); setOriginalText(text);
      } else if (entry) {
        await api.patch(`/knowledge/entries/${entry.id}/deleted`, { expected_version: entry.version, deleted: action === "delete" });
        setEntry(null); setBinary(false); setDirectory(false); setText(""); setOriginalText(""); setPath(""); setOriginalText("");
      }
    },
    onSuccess: () => { void cache.invalidateQueries({ queryKey: ["knowledge"] }); },
  });
  async function open(file: Entry) {
    setEntry(file); setPath(file.path); setDirectory(file.is_directory); setBinary(false); setText(""); setOriginalText("");
    try {
      const result = await api.get<{content: string; version: number}>(`/knowledge/entries/${file.id}/content`);
      setEntry({...file,version:result.version}); setDirectory(file.is_directory); setPath(file.path); setText(result.content); setOriginalText(result.content); setNotice(""); void cache.invalidateQueries({queryKey:["knowledge",sectionId]});
    } catch (error) { setBinary(true); setNotice(errorMessage(error, "Не удалось открыть файл")); }
  }
  return <div className="flex h-full min-h-0 flex-col">
    <PageHeader title="База знаний" />
    <ConfirmDialog open={removeSection} onOpenChange={setRemoveSection} title="Удалить раздел базы знаний?" description="Файлы и история раздела будут удалены. Действие доступно только администратору." confirmLabel="Удалить раздел" danger onConfirm={() => { void api.delete(`/knowledge/sections/${sectionId}`).then(() => {setSectionId("");setEntry(null); setBinary(false); setDirectory(false);setPath("");setText(""); setOriginalText("");setOriginalText("");setRemoveSection(false);void cache.invalidateQueries({queryKey:["knowledge"]});}).catch((error:unknown) => {setRemoveSection(false);setNotice(errorMessage(error,"Не удалось удалить раздел"));}); }} />
    <ConfirmDialog open={pendingChange !== null} onOpenChange={(open) => { if (!open) setPendingChange(null); }} title="Есть несохранённые изменения" description="Продолжить и отменить изменения файла?" confirmLabel="Продолжить" onConfirm={() => { pendingChange?.(); setPendingChange(null); }} />
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto p-4 lg:flex-row">
      <aside className="flex shrink-0 flex-col gap-3 lg:w-72">
        {admin && <div className="flex gap-2"><Input aria-label="Название раздела" value={sectionName} onChange={(e) => setSectionName(e.target.value)} /><Button disabled={!sectionName.trim() || mutation.isPending} onClick={() => mutation.mutate("section")}>Создать</Button></div>}
        <label>Раздел<select className="block w-full rounded border bg-surface p-2" value={sectionId} onChange={(e) => { const next = e.target.value; guard(() => { setSectionId(next); setEntry(null); setBinary(false); setDirectory(false); setPath(""); setText(""); setOriginalText(""); }); }}><option value="">Выберите раздел</option>{sections.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        <Input aria-label="Поиск файлов" placeholder="Поиск по названию и содержимому" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <label><input type="checkbox" checked={trash} onChange={(e) => setTrash(e.target.checked)} /> Корзина</label>
        <KnowledgeTree entries={files.data?.filter((f) => Boolean(f.deleted_at) === trash) ?? []} onOpen={(file) => guard(() => { void open(file); })} />
      </aside>
      <main className="flex min-w-0 flex-1 flex-col gap-3">
        {(sections.error || files.error || mutation.error) && <p role="alert" className="text-danger">{errorMessage(sections.error || files.error || mutation.error, "Не удалось выполнить операцию")}</p>}
        {notice && <p role="alert">{notice}</p>}
        {section && <>{admin && <Button variant="danger" onClick={() => setRemoveSection(true)}>Удалить раздел</Button>}{admin && <div className="flex flex-wrap gap-3"><label><input type="checkbox" checked={section.user_read} onChange={(e) => { void api.patch(`/knowledge/sections/${sectionId}`, {...section, user_read:e.target.checked, user_write:e.target.checked && section.user_write}).then(() => cache.invalidateQueries({queryKey:["knowledge"]})).catch((error:unknown) => setNotice(errorMessage(error,"Не удалось изменить права"))); }} /> Пользователи: чтение</label><label><input type="checkbox" checked={section.user_write} onChange={(e) => { void api.patch(`/knowledge/sections/${sectionId}`, {...section, user_read:section.user_read || e.target.checked, user_write:e.target.checked}).then(() => cache.invalidateQueries({queryKey:["knowledge"]})).catch((error:unknown) => setNotice(errorMessage(error,"Не удалось изменить права"))); }} /> Пользователи: запись</label></div>}<p>{writable ? "Чтение и запись" : "Только чтение"}</p>
          {writable && !files.data?.some((f) => f.path === "README.md") && <Button onClick={() => { void api.put(`/knowledge/sections/${sectionId}/entries`, {path:"README.md",content:"# Карта ресурсов\n\n## Документация\nДобавьте ссылки на источники и название MCP-подключения.\n\n## Репозитории\nДобавьте ссылки и назначение проектов.\n\n## Правила поиска\nУкажите, где проверять актуальность информации.\n",expected_version:0}).then(() => cache.invalidateQueries({queryKey:["knowledge"]})).catch((error:unknown) => setNotice(errorMessage(error,"Не удалось создать карту"))); }}>Создать карту ресурсов</Button>}
          {writable && <Button onClick={() => guard(() => { setEntry(null); setBinary(false); setDirectory(false); setPath(""); setText(""); setOriginalText(""); })}>Новый файл</Button>}
          {writable && !entry && <label><input type="checkbox" checked={directory} onChange={(e) => setDirectory(e.target.checked)} /> Папка</label>}
          {writable && <label>Загрузить файл<input type="file" onChange={(e) => { const file = e.target.files?.[0]; if (!file) return; const body = new FormData(); body.append("file",file); void api.post(`/knowledge/sections/${sectionId}/upload?path=${encodeURIComponent(file.name)}`,body).then(() => cache.invalidateQueries({queryKey:["knowledge"]})).catch((error:unknown) => setNotice(errorMessage(error,"Не удалось загрузить файл"))); }} /></label>}
          <Input aria-label="Путь файла" placeholder="Документы/Карта.md" value={path} disabled={Boolean(entry) || !writable} onChange={(e) => setPath(e.target.value)} />
          <Button onClick={() => setPreview(!preview)}>{preview ? "Редактор" : "Предпросмотр"}</Button>
          {preview ? <AgentMessageText text={text} /> : <Textarea aria-label="Содержимое файла" className="min-h-80 flex-1 font-mono" value={text} disabled={binary || !writable || Boolean(entry?.deleted_at)} onChange={(e) => setText(e.target.value)} />}
          {writable && <div className="flex flex-wrap gap-2"><Button disabled={binary || !path || mutation.isPending || Boolean(entry?.deleted_at)} onClick={() => mutation.mutate("save")}>Сохранить</Button>{entry && <Button disabled={mutation.isPending} onClick={() => mutation.mutate(entry.deleted_at ? "restore" : "delete")}>{entry.deleted_at ? "Восстановить" : "В корзину"}</Button>}</div>}
          {entry && <Button onClick={() => guard(() => { void open(entry); })}>Перечитать файл</Button>}
          {entry && writable && <details><summary>Переименовать или перенести</summary><Input aria-label="Новый путь" value={destination} onChange={(e) => setDestination(e.target.value)} /><select aria-label="Целевой раздел" value={destinationSection || sectionId} onChange={(e) => setDestinationSection(e.target.value)}>{sections.data?.filter((s) => admin || s.user_write).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select><Button disabled={!destination} onClick={() => { void api.patch(`/knowledge/entries/${entry.id}/location`,{section_id:destinationSection || sectionId,path:destination,expected_version:entry.version}).then(() => {setEntry(null); setBinary(false); setDirectory(false);setPath("");setText(""); setOriginalText("");void cache.invalidateQueries({queryKey:["knowledge"]});}).catch((error:unknown) => setNotice(errorMessage(error,"Не удалось перенести файл"))); }}>Перенести</Button></details>}
          {entry && <Button onClick={() => { void api.getBlob(`/knowledge/entries/${entry.id}/download`).then((blob) => { const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href=url; a.download=entry.path.split("/").pop()!; a.click(); URL.revokeObjectURL(url); }).catch((error:unknown) => setNotice(errorMessage(error,"Не удалось скачать файл"))); }}>Скачать</Button>}
          {entry && <details><summary>История изменений</summary>{history.data?.map((v) => <div key={v.version} className="flex flex-wrap gap-2 py-1"><span>v{v.version} · {new Date(v.created_at).toLocaleString()} · {v.created_by} {v.task_id && <a href={`/tasks/${v.task_id}`}>Задача</a>}</span><Button onClick={() => { void api.get<{content:string}>(`/knowledge/entries/${entry.id}/content`, {version:v.version}).then((r) => setText(r.content)).catch((error:unknown) => setNotice(errorMessage(error,"Не удалось прочитать версию"))); }}>Открыть версию</Button></div>)}</details>}
        </>}
      </main>
    </div>
  </div>;
}
