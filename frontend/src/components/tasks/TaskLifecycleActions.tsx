import { useState } from "react";
import { Copy, Eraser, FolderX, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/common/dialogs/ConfirmDialog";
import { DuplicateTaskDialog } from "@/components/tasks/DuplicateTaskDialog";
import { HEADER_BUTTON } from "@/styles/classes";
import { useCleanupRepositories, useClearContext, useResetTask } from "@/hooks/useTasks";
import { toastError } from "@/lib/errors";
import { TaskStatus, type Task } from "@/lib/types";
import { ButtonLabel } from "@/components/common/actions/ButtonLabel";

type PendingAction = "cleanup" | "clear-context" | "reset" | null;

/** Раздел 14.2, 14.3: действия над задачей в `done`/`failed` — очистка
 * директории репозиториев, очистка контекста, возврат в новые, дублирование. */
export function TaskLifecycleActions({ task }: { task: Task }) {
  const [pending, setPending] = useState<PendingAction>(null);
  const [duplicateOpen, setDuplicateOpen] = useState(false);
  const cleanupRepositories = useCleanupRepositories(task.id);
  const clearContext = useClearContext(task.id);
  const resetTask = useResetTask(task.id);
  const isTerminal = task.status === TaskStatus.DONE || task.status === TaskStatus.FAILED;

  function handleCleanup() {
    cleanupRepositories.mutate(undefined, {
      onSuccess: () => {
        setPending(null);
        toast.success("Директория репозиториев очищена");
      },
      onError: toastError("Не удалось очистить репозитории"),
    });
  }

  function handleClearContext() {
    clearContext.mutate(undefined, {
      onSuccess: () => {
        setPending(null);
        toast.success("Контекст очищен — перезапуск начнёт новую сессию");
      },
      onError: toastError("Не удалось очистить контекст"),
    });
  }

  function handleReset() {
    resetTask.mutate(undefined, {
      onSuccess: () => {
        setPending(null);
        toast.success("Задача снова в новых — можно сменить пайплайн и запустить");
      },
      onError: toastError("Не удалось вернуть задачу в новые"),
    });
  }

  return (
    <>
      {isTerminal && (
        <button
          type="button"
          className={HEADER_BUTTON}
          aria-label="Вернуть в новые"
          title="Вернуть в новые"
          onClick={() => setPending("reset")}
        >
          <RotateCcw className="size-3.5" />
          <ButtonLabel>Вернуть в новые</ButtonLabel>
        </button>
      )}
      {task.status === TaskStatus.FAILED && (
        <button
          type="button"
          className={HEADER_BUTTON}
          aria-label="Очистить контекст"
          title="Очистить контекст"
          onClick={() => setPending("clear-context")}
        >
          <Eraser className="size-3.5" />
          <ButtonLabel>Очистить контекст</ButtonLabel>
        </button>
      )}
      {isTerminal && !task.repo_cleaned_at && (
        <button
          type="button"
          className={HEADER_BUTTON}
          aria-label="Очистить репозитории"
          title="Очистить репозитории"
          onClick={() => setPending("cleanup")}
        >
          <FolderX className="size-3.5" />
          <ButtonLabel>Очистить репозитории</ButtonLabel>
        </button>
      )}
      {isTerminal && task.repo_cleaned_at && (
        <span className="hidden text-small text-text-3 sm:inline">Репозитории очищены</span>
      )}
      {task.status === TaskStatus.DONE && (
        <button
          type="button"
          className={HEADER_BUTTON}
          aria-label="Дублировать"
          title="Дублировать"
          onClick={() => setDuplicateOpen(true)}
        >
          <Copy className="size-3.5" />
          <ButtonLabel>Дублировать</ButtonLabel>
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
      <ConfirmDialog
        open={pending === "reset"}
        onOpenChange={(open) => !open && setPending(null)}
        title="Вернуть задачу в новые?"
        description="Можно будет сменить пайплайн и состав нод. «Запустить» пройдёт пайплайн с начала в той же сессии агента; история выполнения сохранится."
        confirmLabel="Вернуть в новые"
        pending={resetTask.isPending}
        onConfirm={handleReset}
      />
      <DuplicateTaskDialog task={task} open={duplicateOpen} onOpenChange={setDuplicateOpen} />
    </>
  );
}
