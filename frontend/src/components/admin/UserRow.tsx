import { Card } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SftpLoginEditor } from "@/components/admin/SftpLoginEditor";
import { UserNumberSettingEditor } from "@/components/admin/UserNumberSettingEditor";
import { MAX_PARALLEL_TASKS_SETTING, RETENTION_SETTINGS } from "@/components/admin/userNumberSettings";
import { SshKeyLine } from "@/components/admin/SshKeyLine";
import { useUpdateUser } from "@/hooks/useAdmin";
import { toastError } from "@/lib/errors";
import { USER_ROLE_LABEL } from "@/lib/labels";
import { UserRole, type User } from "@/lib/types";

/** Пользователь: роль, блокировка, доступ по SFTP, лимит задач и сроки архива (раздел 15.5). */
export function UserRow({ user }: { user: User }) {
  const updateUser = useUpdateUser(user.id);

  return (
    <Card className="flex flex-wrap items-center gap-3">
      <div className="min-w-0 flex-1 basis-48">
        <div className="truncate font-bold" title={user.email}>
          {user.email}
        </div>
        <div className="text-meta text-text-3">
          {new Date(user.created_at).toLocaleDateString("ru-RU")}
        </div>
        <SftpLoginEditor user={user} />
        <UserNumberSettingEditor user={user} setting={MAX_PARALLEL_TASKS_SETTING} />
        {RETENTION_SETTINGS.map((setting) => (
          <UserNumberSettingEditor key={setting.field} user={user} setting={setting} />
        ))}
        <SshKeyLine user={user} />
      </div>
      <Select
        value={user.role}
        onValueChange={(role) =>
          updateUser.mutate(
            { role: role as UserRole },
            {
              onError: toastError("Не удалось изменить роль"),
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
                onError: toastError("Не удалось изменить"),
              },
            )
          }
        />
      </div>
    </Card>
  );
}
