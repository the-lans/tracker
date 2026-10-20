import { useState } from "react";
import { Play, Plus, Square } from "lucide-react";
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
import {
  useAddLibraryPrompt,
  useRunLibraryPrompt,
  useStopManualRequest,
  useTaskLibraryPrompts,
} from "@/hooks/useTasks";
import { SESSION_ACTIVE_STATUSES } from "@/components/tasks/taskStatusMeta";
import { ApiError } from "@/lib/apiClient";
import { formatDateTime } from "@/lib/utils";
import { LibraryPromptRunStatus, type NodeItem, type Task } from "@/lib/types";
import { EmptyState } from "@/components/common/feedback/EmptyState";

const RUN_STATUS_LABEL: Record<LibraryPromptRunStatus, string> = {
  [LibraryPromptRunStatus.NEVER_RUN]: "не запускался",
  [LibraryPromptRunStatus.QUEUED]: "в очереди",
  [LibraryPromptRunStatus.RUNNING]: "выполняется",
  [LibraryPromptRunStatus.SUCCESS]: "успех",
  [LibraryPromptRunStatus.FAILED]: "ошибка",
  [LibraryPromptRunStatus.STOPPED]: "остановлен",
};

/**
 * Раздел 7.3, 15.2: таблица добавленных из библиотеки промтов задачи —
 * название, ▶/■, время последнего запуска и статус (включая `queued`).
 * ■ активна для `queued` (отмена из очереди) и `running` (прерывание).
 */
export function TaskLibraryPromptsCard({
  task,
  libraryNodes,
}: {
  task: Task;
  libraryNodes: NodeItem[];
}) {
  const { data: prompts } = useTaskLibraryPrompts(task.id);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string>("");
  const addLibraryPrompt = useAddLibraryPrompt(task.id);
  const runLibraryPrompt = useRunLibraryPrompt(task.id);
  const stopManualRequest = useStopManualRequest(task.id);
  const sessionActive = SESSION_ACTIVE_STATUSES.includes(task.status);

  function handleAdd() {
    if (!selectedNodeId) return;
    addLibraryPrompt.mutate(selectedNodeId, {
      onSuccess: () => {
        setPickerOpen(false);
        setSelectedNodeId("");
      },
      onError: (error) => {
        toast.error(error instanceof ApiError ? error.message : "Не удалось добавить промт");
      },
    });
  }

  function handleRun(taskLibraryPromptId: string) {
    runLibraryPrompt.mutate(taskLibraryPromptId, {
      onSuccess: () => toast.success("Промт поставлен на выполнение"),
      onError: (error) => {
        toast.error(error instanceof ApiError ? error.message : "Не удалось запустить промт");
      },
    });
  }

  function handleStop(requestId: string) {
    stopManualRequest.mutate(requestId, {
      onSuccess: () => toast.success("Промт останавливается"),
      onError: (error) => {
        toast.error(error instanceof ApiError ? error.message : "Не удалось остановить промт");
      },
    });
  }

  return (
    <Card>
      <CardTitle>Системные промты задачи</CardTitle>
      <div className="flex flex-col">
        {(prompts ?? []).map((prompt) => {
          const activeRequestId = prompt.active_request_id;
          return (
            <div
              key={prompt.id}
              className="flex items-center gap-2 border-t border-border py-1.5 first:border-t-0"
            >
              <button
                type="button"
                onClick={() => handleRun(prompt.id)}
                disabled={!sessionActive || runLibraryPrompt.isPending}
                className="flex touch-target size-6 shrink-0 items-center justify-center rounded-[7px] border border-border text-text-2 disabled:opacity-40"
                aria-label="Выполнить промт"
                title={sessionActive ? "Выполнить" : "Сессия задачи не активна"}
              >
                <Play className="size-2.5" fill="currentColor" />
              </button>
              <button
                type="button"
                onClick={() => activeRequestId && handleStop(activeRequestId)}
                disabled={!activeRequestId || stopManualRequest.isPending}
                className="flex touch-target size-6 shrink-0 items-center justify-center rounded-[7px] border border-border text-text-2 disabled:opacity-40"
                aria-label="Остановить промт"
              >
                <Square className="size-2.5" fill="currentColor" />
              </button>
              <div className="min-w-0 flex-1">
                <div className="truncate text-note font-bold" title={prompt.name}>{prompt.name}</div>
                {prompt.last_run_at && (
                  <div className="text-caption text-text-3">{formatDateTime(prompt.last_run_at)}</div>
                )}
              </div>
              <span className="rounded-full bg-surface-2 px-2 py-0.5 text-caption font-bold text-text-3">
                {RUN_STATUS_LABEL[prompt.last_run_status]}
              </span>
            </div>
          );
        })}
        {prompts?.length === 0 && (
          <EmptyState
            compact
            title="Промты из библиотеки не добавлены"
            hint="Нажмите «+ Добавить промт из библиотеки» ниже — промт появится здесь, и его можно будет запускать в этой задаче кнопкой ▶."
          />
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
          {libraryNodes.length === 0 && (
            <EmptyState
              compact
              title="В библиотеке пока нет промтов"
              hint="Сохраните промт, слэш-команду или скрипт в разделе «Библиотека промтов» кнопкой «+ Промт» — после этого его можно будет добавить в задачу."
            />
          )}
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

