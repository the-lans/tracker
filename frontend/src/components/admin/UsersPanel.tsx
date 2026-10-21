import { useState } from "react";
import { Copy, KeyRound, Plus } from "lucide-react";
import { toast } from "sonner";
import { Card, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  useAllowedEmails,
  useCreateAllowedEmail,
  useDeleteAllowedEmail,
  useUpdateUser,
  useUsers,
} from "@/hooks/useAdmin";
import { ApiError } from "@/lib/apiClient";
import { copyText } from "@/lib/textExport";
import { UserRole, type User } from "@/lib/types";
import { ConfirmDeleteButton } from "@/components/common/actions/ConfirmDeleteButton";
import { USER_ROLE_LABEL } from "@/lib/labels";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { SectionTitle } from "@/components/common/typography/SectionTitle";

/**
 * Раздел 15.1, 15.5: ключ sshfs пользователя. До появления `User-Provisioner`
 * администратор ставит его на сервер вручную (решение №16 плана).
 */
function SshKeyLine({ user }: { user: User }) {
  if (user.ssh_public_key === null) {
    return <div className="text-meta text-text-3">SSH-ключ не добавлен</div>;
  }
  const publicKey = user.ssh_public_key;
  return (
    <div className="flex min-w-0 items-center gap-1 text-meta text-text-3">
      <KeyRound className="size-3.5 shrink-0" />
      <span className="truncate font-mono" title={publicKey}>
        {user.ssh_key_fingerprint}
      </span>
      <button
        type="button"
        className="touch-target flex shrink-0 items-center justify-center hover:text-accent"
        aria-label={`Копировать SSH-ключ ${user.email}`}
        title="Копировать ключ"
        onClick={() => copyText(publicKey)}
      >
        <Copy className="size-3.5" />
      </button>
    </div>
  );
}

function UserRow({ user }: { user: User }) {
  const updateUser = useUpdateUser(user.id);

  return (
    <Card className="flex flex-wrap items-center gap-3">
      <div className="min-w-0 flex-1 basis-48">
        <div className="truncate font-bold" title={user.email}>{user.email}</div>
        <div className="text-meta text-text-3">
          {new Date(user.created_at).toLocaleDateString("ru-RU")}
          {" · Linux-логин: "}
          {user.os_username ?? "не назначен"}
        </div>
        <SshKeyLine user={user} />
      </div>
      <Select
        value={user.role}
        onValueChange={(role) =>
          updateUser.mutate(
            { role: role as UserRole },
            {
              onError: (error) =>
                toast.error(error instanceof ApiError ? error.message : "Не удалось изменить роль"),
            },
          )
        }
      >
        <SelectTrigger className="w-32">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={UserRole.USER}>{USER_ROLE_LABEL[UserRole.USER]}</SelectItem>
          <SelectItem value={UserRole.ADMIN}>{USER_ROLE_LABEL[UserRole.ADMIN]}</SelectItem>
        </SelectContent>
      </Select>
      <div className="flex items-center gap-2">
        <span className="text-small text-text-3">
          {user.is_active ? "активен" : "заблокирован"}
        </span>
        <Switch
          checked={user.is_active}
          onCheckedChange={(checked) =>
            updateUser.mutate(
              { is_active: checked },
              {
                onError: (error) =>
                  toast.error(error instanceof ApiError ? error.message : "Не удалось изменить"),
              },
            )
          }
        />
      </div>
    </Card>
  );
}

export function UsersPanel() {
  const { data: users, isLoading } = useUsers();
  const { data: allowedEmails } = useAllowedEmails();
  const createAllowedEmail = useCreateAllowedEmail();
  const deleteAllowedEmail = useDeleteAllowedEmail();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");

  return (
    <div className="flex flex-col gap-5">
      <div>
        <SectionTitle className="mb-2">Пользователи</SectionTitle>
        {isLoading && <LoadingState />}
        <div className="flex flex-col gap-2">
          {(users ?? []).map((user) => (
            <UserRow key={user.id} user={user} />
          ))}
        </div>
      </div>

      <Card>
        <CardTitle>
          <span>Список допуска (e-mail)</span>
          <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
            <Plus className="size-3.5" /> Добавить
          </Button>
        </CardTitle>
        <div className="mb-1 text-small text-text-3">
          Удалённый из списка e-mail блокирует учётную запись при ближайшей ежедневной проверке;
          Linux-логин пользователя после этого нужно заблокировать на сервере вручную.
        </div>
        <div className="flex flex-col">
          {(allowedEmails ?? []).length === 0 && (
            <EmptyState
              compact
              title="Список допуска пуст"
              hint="Нажмите «+ Добавить» и укажите e-mail: войти в трекер через Google смогут только адреса из этого списка."
            />
          )}
          {(allowedEmails ?? []).map((entry) => (
            <div key={entry.id} className="flex items-center gap-2 border-t border-border py-1.5 first:border-t-0">
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
                    onError: (error) =>
                      toast.error(error instanceof ApiError ? error.message : "Не удалось удалить"),
                  })}
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
                  onError: (error) =>
                    toast.error(error instanceof ApiError ? error.message : "Не удалось добавить"),
                })
              }
              disabled={!email || createAllowedEmail.isPending}
            >
              Добавить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
