import { useState } from "react";
import { Eye, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  useDeleteTaskEnvVariable,
  useRevealTaskEnvVariable,
  useUpdateTaskEnvVariable,
} from "@/hooks/useTaskEnvVariables";
import { toastError } from "@/lib/errors";
import type { TaskEnvVariable } from "@/lib/types";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";

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
      onError: toastError("Не удалось показать значение"),
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
        onError: toastError("Не удалось сохранить значение"),
      },
    );
  }

  return (
    <div className="flex flex-col gap-1 border-t border-border py-2 first:border-t-0">
      <div className="flex min-w-0 items-center gap-1">
        <div className="min-w-0 flex-1 truncate font-mono text-small font-bold" title={variable.key}>
          {variable.key}
        </div>
        {!readOnly && !editing && (
          <>
            <Button
              size="icon"
              variant="ghost"
              aria-label={`Изменить ${variable.key}`}
              onClick={() => setEditing(true)}
            >
              <Pencil className="size-3.5" />
            </Button>
            <ConfirmDeleteButton
              kind="переменную"
              name={variable.key}
              pending={remove.isPending}
              iconClassName="size-3.5"
              onConfirm={() =>
                remove.mutate(variable.id, { onError: toastError("Не удалось удалить переменную") })}
            />
          </>
        )}
      </div>
      {editing ? (
        <div className="flex w-full flex-wrap items-center gap-2">
          <Input
            autoFocus
            aria-label={`Новое значение ${variable.key}`}
            className="min-w-0 flex-1"
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
        <div className="flex min-w-0 items-center gap-2">
          <div className="min-w-0 flex-1 truncate font-mono text-small text-text-3" title={revealed ?? undefined}>
            {revealed ?? "••••••"}
          </div>
          {revealed === null && (
            <Button size="sm" variant="ghost" onClick={handleReveal} disabled={reveal.isPending}>
              <Eye className="size-3.5" /> Показать
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
