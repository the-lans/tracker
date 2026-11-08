import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useUpdateUser } from "@/hooks/useAdmin";
import { toastError } from "@/lib/errors";
import type { User } from "@/lib/types";

/** Раздел 3.1, 15.5: границы лимита — как у `UserUpdateRequest.max_parallel_tasks` backend. */
export const MIN_PARALLEL_TASKS = 1;
export const MAX_PARALLEL_TASKS = 50;

function parseLimit(draft: string): number | null {
  const value = Number(draft);
  if (!Number.isInteger(value) || value < MIN_PARALLEL_TASKS || value > MAX_PARALLEL_TASKS) return null;
  return value;
}

/**
 * Раздел 14.4, 15.5: лимит параллельных задач пользователя задаёт
 * администратор; сохраняется по уходу с поля или Enter.
 */
export function UserTaskLimitEditor({ user }: { user: User }) {
  const updateUser = useUpdateUser(user.id);
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? String(user.max_parallel_tasks);
  const parsed = parseLimit(shown);
  const inputId = `max-parallel-${user.id}`;

  function save() {
    if (draft === null) return;
    if (parsed === null || parsed === user.max_parallel_tasks) {
      setDraft(null);
      return;
    }
    updateUser.mutate(
      { max_parallel_tasks: parsed },
      {
        onSettled: () => setDraft(null),
        onError: toastError("Не удалось сохранить лимит"),
      },
    );
  }

  return (
    <div className="flex items-center gap-2 text-meta text-text-3">
      <Label htmlFor={inputId} className="text-meta font-normal text-text-3">
        Параллельных задач:
      </Label>
      <Input
        id={inputId}
        type="number"
        inputMode="numeric"
        min={MIN_PARALLEL_TASKS}
        max={MAX_PARALLEL_TASKS}
        className="h-8 w-20"
        value={shown}
        disabled={updateUser.isPending}
        aria-label={`Параллельных задач ${user.email}`}
        aria-invalid={parsed === null}
        title={`От ${MIN_PARALLEL_TASKS} до ${MAX_PARALLEL_TASKS}`}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={save}
        onKeyDown={(event) => {
          if (event.key === "Enter") save();
          if (event.key === "Escape") setDraft(null);
        }}
      />
    </div>
  );
}
