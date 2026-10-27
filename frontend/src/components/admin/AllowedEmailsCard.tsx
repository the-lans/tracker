import { useState } from "react";
import { Plus } from "lucide-react";
import { Card, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAllowedEmails, useCreateAllowedEmail, useDeleteAllowedEmail } from "@/hooks/useAdmin";
import { toastError } from "@/lib/errors";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { LoadingState } from "@/components/common/feedback/LoadingState";

/** Раздел 19.1: список допуска — войти через Google могут только эти адреса. */
export function AllowedEmailsCard() {
  const { data: allowedEmails, isLoading } = useAllowedEmails();
  const createAllowedEmail = useCreateAllowedEmail();
  const deleteAllowedEmail = useDeleteAllowedEmail();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");

  return (
    <>
      <Card>
        <CardTitle>
          <span>Список допуска (e-mail)</span>
          <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
            <Plus className="size-3.5" /> Добавить
          </Button>
        </CardTitle>
        <div className="mb-1 text-small text-text-3">
          Удалённый из списка e-mail блокирует учётную запись при ближайшей ежедневной проверке:
          закрываются вход в трекер и доступ по SFTP.
        </div>
        <div className="flex flex-col">
          {isLoading && <LoadingState />}
          {allowedEmails?.length === 0 && (
            <EmptyState
              compact
              title="Список допуска пуст"
              hint="Нажмите «+ Добавить» и укажите e-mail: войти в трекер через Google смогут только адреса из этого списка."
            />
          )}
          {(allowedEmails ?? []).map((entry) => (
            <div
              key={entry.id}
              className="flex items-center gap-2 border-t border-border py-1.5 first:border-t-0"
            >
              <span className="min-w-0 flex-1 truncate text-body" title={entry.email}>
                {entry.email}
              </span>
              <ConfirmDeleteButton
                kind="e-mail из списка допуска"
                name={entry.email}
                pending={deleteAllowedEmail.isPending}
                iconClassName="size-3.5"
                onConfirm={() =>
                  deleteAllowedEmail.mutate(entry.id, {
                    onError: toastError("Не удалось удалить"),
                  })
                }
              />
            </div>
          ))}
        </div>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Разрешить email</DialogTitle>
          </DialogHeader>
          <Input
            placeholder="user@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <DialogFooter>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Отмена
            </Button>
            <Button
              onClick={() =>
                createAllowedEmail.mutate(email, {
                  onSuccess: () => {
                    setOpen(false);
                    setEmail("");
                  },
                  onError: toastError("Не удалось добавить"),
                })
              }
              disabled={!email || createAllowedEmail.isPending}
            >
              Добавить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
