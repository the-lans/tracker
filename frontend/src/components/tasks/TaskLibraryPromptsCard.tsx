import { useState } from "react";
import { Play, Plus } from "lucide-react";
import { toast } from "sonner";
import { Card, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAddLibraryPrompt, useRunLibraryPrompt } from "@/hooks/useTasks";
import { ApiError } from "@/lib/apiClient";
import { LibraryPromptRunStatus, type NodeItem, type Task } from "@/lib/types";

const RUN_STATUS_LABEL: Record<LibraryPromptRunStatus, string> = {
  [LibraryPromptRunStatus.NEVER_RUN]: "не запускался",
  [LibraryPromptRunStatus.QUEUED]: "в очереди",
  [LibraryPromptRunStatus.RUNNING]: "выполняется",
  [LibraryPromptRunStatus.SUCCESS]: "успех",
  [LibraryPromptRunStatus.FAILED]: "ошибка",
  [LibraryPromptRunStatus.STOPPED]: "остановлен",
};

/**
 * Раздел 15.2: таблица добавленных из библиотеки промтов задачи.
 *
 * Backend не отдаёт список уже добавленных `task_library_prompts` задачи
 * отдельным GET-эндпоинтом — есть только POST (добавить) и POST .../run.
 * Добавленные в рамках текущей сессии просмотра промты хранятся здесь в
 * локальном состоянии; при перезагрузке страницы список сбрасывается. Это
 * реальное ограничение backend API, не сокращение объёма фронтенда — см.
 * итоговый отчёт по Этапу 13.
 */
export function TaskLibraryPromptsCard({
  task,
  libraryNodes,
}: {
  task: Task;
  libraryNodes: NodeItem[];
}) {
  const [added, setAdded] = useState<{ id: string; nodeId: string; nodeName: string }[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string>("");
  const addLibraryPrompt = useAddLibraryPrompt(task.id);
  const runLibraryPrompt = useRunLibraryPrompt(task.id);
  const [runningIds, setRunningIds] = useState<Set<string>>(new Set());

  function handleAdd() {
    if (!selectedNodeId) return;
    addLibraryPrompt.mutate(selectedNodeId, {
      onSuccess: (response) => {
        const node = libraryNodes.find((item) => item.id === selectedNodeId);
        setAdded((prev) => [
          ...prev,
          { id: response.id, nodeId: selectedNodeId, nodeName: node?.name ?? "Промт" },
        ]);
        setPickerOpen(false);
        setSelectedNodeId("");
      },
      onError: (error) => {
        toast.error(error instanceof ApiError ? error.message : "Не удалось добавить промт");
      },
    });
  }

  function handleRun(taskLibraryPromptId: string) {
    setRunningIds((prev) => new Set(prev).add(taskLibraryPromptId));
    runLibraryPrompt.mutate(taskLibraryPromptId, {
      onSuccess: () => toast.success("Промт поставлен на выполнение"),
      onError: (error) => {
        toast.error(error instanceof ApiError ? error.message : "Не удалось запустить промт");
      },
      onSettled: () => {
        setRunningIds((prev) => {
          const next = new Set(prev);
          next.delete(taskLibraryPromptId);
          return next;
        });
      },
    });
  }

  return (
    <Card>
      <CardTitle>Системные промты задачи</CardTitle>
      <div className="flex flex-col">
        {added.map((entry) => (
          <div
            key={entry.id}
            className="flex items-center gap-2 border-t border-border py-1.5 first:border-t-0"
          >
            <button
              type="button"
              onClick={() => handleRun(entry.id)}
              disabled={runningIds.has(entry.id)}
              className="flex touch-target size-6 shrink-0 items-center justify-center rounded-[7px] border border-border text-text-2"
              aria-label="Запустить"
            >
              <Play className="size-2.5" fill="currentColor" />
            </button>
            <div className="flex-1 truncate text-[12.5px] font-bold">{entry.nodeName}</div>
            <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[10.5px] font-bold text-text-3">
              {RUN_STATUS_LABEL[LibraryPromptRunStatus.QUEUED]}
            </span>
          </div>
        ))}
        {added.length === 0 && (
          <div className="py-2 text-[12.5px] text-text-3">Промты из библиотеки не добавлены</div>
        )}
      </div>
      <Button size="sm" variant="secondary" className="mt-2" onClick={() => setPickerOpen(true)}>
        <Plus className="size-4" />
        Добавить промт из библиотеки
      </Button>

      <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Добавить промт из библиотеки</DialogTitle>
          </DialogHeader>
          <Select value={selectedNodeId} onValueChange={setSelectedNodeId}>
            <SelectTrigger>
              <SelectValue placeholder="Выберите промт" />
            </SelectTrigger>
            <SelectContent>
              {libraryNodes.map((node) => (
                <SelectItem key={node.id} value={node.id}>
                  {node.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setPickerOpen(false)}>
              Отмена
            </Button>
            <Button onClick={handleAdd} disabled={!selectedNodeId || addLibraryPrompt.isPending}>
              Добавить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

