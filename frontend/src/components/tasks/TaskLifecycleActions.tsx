import { useState } from "react";
import { Copy, Eraser, FolderX } from "lucide-react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { DuplicateTaskDialog } from "@/components/tasks/DuplicateTaskDialog";
import { HEADER_BUTTON } from "@/components/tasks/headerButton";
import { useCleanupRepositories, useClearContext } from "@/hooks/useTasks";
import { ApiError } from "@/lib/apiClient";
import { TaskStatus, type Task } from "@/lib/types";

type PendingAction = "cleanup" | "clear-context" | null;

function onError(fallback: string) {
  return (error: Error) => toast.error(error instanceof ApiError ? error.message : fallback);
}

/** Раздел 14.2, 14.3: действия над задачей в `done`/`failed` — очистка
 * директории репозиториев, очистка контекста, дублирование. */
export function TaskLifecycleActions({ task }: { task: Task }) {
  const [pending, setPending] = useState<PendingAction>(null);
  const [duplicateOpen, setDuplicateOpen] = useState(false);
  const cleanupRepositories = useCleanupRepositories(task.id);
  const clearContext = useClearContext(task.id);
  const isTerminal = task.status === TaskStatus.DONE || task.status === TaskStatus.FAILED;

  function handleCleanup() {
    cleanupRepositories.mutate(undefined, {
      onSuccess: () => {
        setPending(null);
        toast.success("Директория репозиториев очищена");
      },
      onError: onError("Не удалось очистить репозитории"),
    });
  }

  function handleClearContext() {
    clearContext.mutate(undefined, {
      onSuccess: () => {
        setPending(null);
        toast.success("Контекст очищен — перезапуск начнёт новую сессию");
      },
      onError: onError("Не удалось очистить контекст"),
    });
  }

  return (
    <>
      {task.status === TaskStatus.FAILED && (
        <button type="button" className={HEADER_BUTTON} onClick={() => setPending("clear-context")}>
          <Eraser className="size-3.5" />
          <span className="hidden sm:inline">Очистить контекст</span>
        </button>
      )}
      {isTerminal && !task.repo_cleaned_at && (
        <button type="button" className={HEADER_BUTTON} onClick={() => setPending("cleanup")}>
          <FolderX className="size-3.5" />
          <span className="hidden sm:inline">Очистить репозитории</span>
        </button>
      )}
      {isTerminal && task.repo_cleaned_at && (
        <span className="hidden text-[12px] text-text-3 sm:inline">Репозитории очищены</span>
      )}
      {task.status === TaskStatus.DONE && (
        <button type="button" className={HEADER_BUTTON} onClick={() => setDuplicateOpen(true)}>
          <Copy className="size-3.5" />
          <span className="hidden sm:inline">Дублировать</span>
        </button>
      )}

      <ConfirmDialog
        open={pending === "cleanup"}
        onOpenChange={(open) => !open && setPending(null)}
        title="Очистить директорию репозиториев?"
        description="Клоны репозиториев задачи будут удалены с сервера. Незапушенные изменения пропадут; пользовательские файлы задачи останутся. При перезапуске репозитории склонируются заново."
        confirmLabel="Очистить"
        danger
        pending={cleanupRepositories.isPending}
        onConfirm={handleCleanup}
      />
      <ConfirmDialog
        open={pending === "clear-context"}
        onOpenChange={(open) => !open && setPending(null)}
        title="Очистить контекст сессии?"
        description="Агент забудет историю диалога. «Перезапустить с текущей ноды» начнёт новую сессию."
        confirmLabel="Очистить контекст"
        danger
        pending={clearContext.isPending}
        onConfirm={handleClearContext}
      />
      <DuplicateTaskDialog task={task} open={duplicateOpen} onOpenChange={setDuplicateOpen} />
    </>
  );
}
