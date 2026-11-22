import { useState, type KeyboardEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { useUpdateTask } from "@/hooks/useTasks";
import { toastError } from "@/lib/errors";
import type { Task } from "@/lib/types";

/**
 * Правка описания задачи прямо в карточке (раздел 12.1, 15.2). Сохраняет текст;
 * отрисованное описание Jira после правки не показывается, вернуть его можно
 * кнопкой «Обновить из Jira».
 */
export function TaskDescriptionEditor({ task, onClose }: { task: Task; onClose: () => void }) {
  const [text, setText] = useState(task.description);
  const updateTask = useUpdateTask(task.id);
  // Концевые пробелы и переводы строк не сохраняются (как и на сервере).
  const trimmed = text.trimEnd();
  const canSave = trimmed !== task.description && !updateTask.isPending;

  function save() {
    if (!canSave) return;
    updateTask.mutate(
      { description: trimmed },
      {
        onSuccess: () => {
          toast.success("Описание сохранено");
          onClose();
        },
        onError: toastError("Не удалось сохранить описание"),
      },
    );
  }

  // Escape обрабатывает окно (TaskDetailsDialog): Radix ловит его раньше поля.
  function handleKeyDown(event: KeyboardEvent) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      save();
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <Textarea
        aria-label="Описание задачи"
        value={text}
        rows={10}
        autoFocus
        onChange={(event) => setText(event.target.value)}
        onKeyDown={handleKeyDown}
      />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={onClose}>
          Отмена
        </Button>
        <Button type="button" size="sm" disabled={!canSave} onClick={save}>
          Сохранить
        </Button>
      </div>
    </div>
  );
}
