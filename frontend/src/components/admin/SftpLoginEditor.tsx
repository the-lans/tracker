import { useState } from "react";
import { Check, Pencil, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useUpdateUser } from "@/hooks/useAdmin";
import { toastError } from "@/lib/errors";
import type { User } from "@/lib/types";

/** Раздел 3.1, 15.5: логин SFTP-шлюза назначает администратор. */
export function SftpLoginEditor({ user }: { user: User }) {
  const updateUser = useUpdateUser(user.id);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  function handleSave() {
    updateUser.mutate(
      { os_username: draft.trim() },
      {
        onSuccess: () => setEditing(false),
        onError: toastError("Не удалось сохранить логин"),
      },
    );
  }

  if (editing) {
    return (
      <div className="flex items-center gap-1">
        <Input
          aria-label={`Логин SFTP ${user.email}`}
          className="h-8 max-w-48 font-mono"
          placeholder="ivan"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <Button
          size="icon"
          variant="ghost"
          aria-label="Сохранить логин"
          disabled={!draft.trim() || updateUser.isPending}
          onClick={handleSave}
        >
          <Check className="size-4" />
        </Button>
        <Button size="icon" variant="ghost" aria-label="Отмена" onClick={() => setEditing(false)}>
          <X className="size-4" />
        </Button>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1 text-meta text-text-3">
      <span>Логин SFTP: </span>
      {user.os_username ? (
        <span className="font-mono">{user.os_username}</span>
      ) : (
        <span>не назначен</span>
      )}
      <button
        type="button"
        className="touch-target flex shrink-0 items-center justify-center hover:text-accent"
        aria-label={`Изменить логин SFTP ${user.email}`}
        title="Изменить логин"
        onClick={() => {
          setDraft(user.os_username ?? "");
          setEditing(true);
        }}
      >
        <Pencil className="size-3.5" />
      </button>
    </div>
  );
}
