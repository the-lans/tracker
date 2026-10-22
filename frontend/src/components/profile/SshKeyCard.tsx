import { useState } from "react";
import { KeyRound } from "lucide-react";
import { toast } from "sonner";
import { Card, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/input";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { useDeleteSshKey, useProfile, useUpdateSshKey } from "@/hooks/useProfile";
import { ApiError } from "@/lib/apiClient";

function keyTitle(publicKey: string): string {
  const [keyType, , ...comment] = publicKey.split(" ");
  return comment.length > 0 ? `${keyType} · ${comment.join(" ")}` : keyType;
}

/**
 * Раздел 15.1: публичный SSH-ключ для доступа к файлам задач по SFTP.
 * Один ключ на пользователя; действует сразу после сохранения.
 */
export function SshKeyCard() {
  const { data: profile, isLoading } = useProfile();
  const updateSshKey = useUpdateSshKey();
  const deleteSshKey = useDeleteSshKey();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const onError = (error: unknown) =>
    toast.error(error instanceof ApiError ? error.message : "Не удалось сохранить ключ");

  function handleSave() {
    updateSshKey.mutate(
      { public_key: draft },
      {
        onSuccess: () => {
          setEditing(false);
          setDraft("");
          toast.success("Ключ сохранён — доступ по SFTP открыт");
        },
        onError,
      },
    );
  }

  const publicKey = profile?.ssh_public_key ?? null;
  const showForm = editing || (!isLoading && publicKey === null);

  return (
    <Card>
      <CardTitle>SSH-ключ для SFTP</CardTitle>
      {isLoading && <LoadingState />}
      {publicKey !== null && !editing && (
        <div className="flex flex-wrap items-center gap-3">
          <KeyRound className="size-4 shrink-0 text-text-2" />
          <div className="min-w-0 flex-1 basis-56">
            <div className="truncate text-body font-bold" title={publicKey}>
              {keyTitle(publicKey)}
            </div>
            <div className="truncate font-mono text-small text-text-3">
              {profile?.ssh_key_fingerprint}
            </div>
          </div>
          <Button variant="secondary" onClick={() => setEditing(true)}>
            Заменить
          </Button>
          <ConfirmDeleteButton
            kind="SSH-ключ"
            name={keyTitle(publicKey)}
            pending={deleteSshKey.isPending}
            onConfirm={() => deleteSshKey.mutate(undefined, { onError })}
          />
        </div>
      )}
      {showForm && (
        <div className="flex flex-col gap-2">
          {publicKey === null && !editing && (
            <EmptyState
              compact
              title="Ключ не добавлен"
              hint="Вставьте публичный ключ — содержимое файла ~/.ssh/id_ed25519.pub. Приватный ключ остаётся у вас."
            />
          )}
          <Label htmlFor="ssh-public-key">Публичный ключ</Label>
          <Textarea
            id="ssh-public-key"
            rows={3}
            className="font-mono text-small"
            placeholder="ssh-ed25519 AAAA… user@example.com"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <div className="flex flex-wrap justify-end gap-2">
            {editing && (
              <Button variant="secondary" onClick={() => setEditing(false)}>
                Отмена
              </Button>
            )}
            <Button onClick={handleSave} disabled={!draft.trim() || updateSshKey.isPending}>
              Сохранить ключ
            </Button>
          </div>
        </div>
      )}
      <div className="mt-2 text-small text-text-3">
        Новый ключ действует сразу, прежний после замены или удаления перестаёт работать.
      </div>
    </Card>
  );
}
