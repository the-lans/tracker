import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
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
import { UserRole, type User } from "@/lib/types";

function UserRow({ user }: { user: User }) {
  const updateUser = useUpdateUser(user.id);

  return (
    <Card className="flex flex-wrap items-center gap-3">
      <div className="min-w-0 flex-1">
        <div className="truncate font-bold">{user.email}</div>
        <div className="text-[11.5px] text-text-3">
          {new Date(user.created_at).toLocaleDateString("ru-RU")}
        </div>
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
          <SelectItem value={UserRole.USER}>user</SelectItem>
          <SelectItem value={UserRole.ADMIN}>admin</SelectItem>
        </SelectContent>
      </Select>
      <div className="flex items-center gap-2">
        <span className="text-[12px] text-text-3">активен</span>
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
        <div className="mb-2 text-[12.5px] font-extrabold text-text-2">Пользователи</div>
        {isLoading && <div className="text-text-3">Загрузка…</div>}
        <div className="flex flex-col gap-2">
          {(users ?? []).map((user) => (
            <UserRow key={user.id} user={user} />
          ))}
        </div>
      </div>

      <Card>
        <CardTitle>
          <span>allowed_emails</span>
          <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
            <Plus className="size-3.5" /> Добавить
          </Button>
        </CardTitle>
        <div className="flex flex-col">
          {(allowedEmails ?? []).map((entry) => (
            <div key={entry.id} className="flex items-center gap-2 border-t border-border py-1.5 first:border-t-0">
              <span className="flex-1 text-[13px]">{entry.email}</span>
              <button
                type="button"
                onClick={() =>
                  deleteAllowedEmail.mutate(entry.id, {
                    onError: (error) =>
                      toast.error(error instanceof ApiError ? error.message : "Не удалось удалить"),
                  })
                }
                className="touch-target flex items-center justify-center text-text-3 hover:text-danger"
              >
                <Trash2 className="size-3.5" />
              </button>
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
