import { useState } from "react";
import { Eye, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  useDeleteTaskEnvVariable,
  useRevealTaskEnvVariable,
  useUpdateTaskEnvVariable,
} from "@/hooks/useTaskEnvVariables";
import { ApiError } from "@/lib/apiClient";
import type { TaskEnvVariable } from "@/lib/types";

function onError(fallback: string) {
  return (error: Error) => toast.error(error instanceof ApiError ? error.message : fallback);
}

/** Одна переменная задачи: значение скрыто, пока не нажато «Показать» (правило 8). */
export function TaskEnvVariableRow({
  taskId,
  variable,
  readOnly,
}: {
  taskId: string;
  variable: TaskEnvVariable;
  readOnly: boolean;
}) {
  const [revealed, setRevealed] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const reveal = useRevealTaskEnvVariable(taskId);
  const update = useUpdateTaskEnvVariable(taskId);
  const remove = useDeleteTaskEnvVariable(taskId);

  function handleReveal() {
    reveal.mutate(variable.id, {
      onSuccess: (data) => setRevealed(data.value),
      onError: onError("Не удалось показать значение"),
    });
  }

  function handleSave() {
    update.mutate(
      { variableId: variable.id, value: draft },
      {
        onSuccess: () => {
          setEditing(false);
          setRevealed(null);
          setDraft("");
        },
        onError: onError("Не удалось сохранить значение"),
      },
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-border py-2 first:border-t-0">
      <div className="font-mono text-[12px] font-bold">{variable.key}</div>
      {editing ? (
        <div className="flex w-full items-center gap-2">
          <Input
            autoFocus
            aria-label={`Новое значение ${variable.key}`}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <Button size="sm" onClick={handleSave} disabled={update.isPending}>
            Сохранить
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setEditing(false)}>
            Отмена
          </Button>
        </div>
      ) : (
        <>
          <div className="min-w-0 flex-1 truncate font-mono text-[12px] text-text-3">
            {revealed ?? "••••••"}
          </div>
          {revealed === null && (
            <Button size="sm" variant="ghost" onClick={handleReveal} disabled={reveal.isPending}>
              <Eye className="size-3.5" /> Показать
            </Button>
          )}
          {!readOnly && (
            <>
              <Button
                size="icon"
                variant="ghost"
                aria-label={`Изменить ${variable.key}`}
                onClick={() => setEditing(true)}
              >
                <Pencil className="size-3.5" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                aria-label={`Удалить ${variable.key}`}
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(variable.id, { onError: onError("Не удалось удалить переменную") })
                }
              >
                <Trash2 className="size-3.5" />
              </Button>
            </>
          )}
        </>
      )}
    </div>
  );
}
