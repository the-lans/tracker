import { useState, type FormEvent } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { TaskRepositoryPicker } from "@/components/tasks/TaskRepositoryPicker";
import { useAddTaskRepositories } from "@/hooks/useTasks";
import { toastError } from "@/lib/errors";
import { RepositoryRole, type TaskRepositoryAttach } from "@/lib/types";

/**
 * Раздел 3.2: репозитории, которые понадобились по ходу задачи. По умолчанию —
 * «только чтение»: чаще всего их добавляют, чтобы собрать контекст.
 */
export function AddTaskRepositoriesDialog({
  taskId,
  attachedIds,
  open,
  onOpenChange,
}: {
  taskId: string;
  attachedIds: ReadonlySet<string>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [selected, setSelected] = useState<TaskRepositoryAttach[]>([]);
  const addRepositories = useAddTaskRepositories(taskId);

  function close() {
    setSelected([]);
    onOpenChange(false);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    addRepositories.mutate(
      { repositories: selected },
      { onSuccess: close, onError: toastError("Не удалось добавить репозитории") },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Добавить репозитории</DialogTitle>
          <DialogDescription className="text-note text-text-3">
            Репозиторий склонируется перед следующей нодой или при следующем запуске, агент
            получит об этом служебное сообщение. MCP-серверы шаблона репозитория подключатся при
            следующем старте сессии.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <TaskRepositoryPicker
            value={selected}
            onChange={setSelected}
            excludeIds={attachedIds}
            defaultRole={RepositoryRole.READ_ONLY}
          />
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={close}>
              Отмена
            </Button>
            <Button type="submit" disabled={!selected.length || addRepositories.isPending}>
              Добавить
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
