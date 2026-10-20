import { LogOut } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { ActiveSessionsCard } from "@/components/profile/ActiveSessionsCard";
import { Card, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { initialsFromEmail } from "@/lib/utils";
import { useAuth } from "@/stores/authStore";

export function ProfilePage() {
  const { user, logout } = useAuth();
  if (!user) return null;

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Профиль" />
      <div className="min-h-0 flex-1 overflow-auto px-5 pb-8 lg:px-8">
        <div className="flex max-w-lg flex-col gap-4">
          <Card className="flex items-center gap-3.5">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#4f5fe0] to-[#8b5cf0] text-[16px] font-extrabold text-white">
              {initialsFromEmail(user.email)}
            </div>
            <div>
              <div className="font-bold">{user.email}</div>
              <div className="text-[12px] text-text-3">{user.role}</div>
            </div>
          </Card>

          <Card>
            <CardTitle>SSH-ключ для sshfs</CardTitle>
            <div className="text-[13px] text-text-3">
              Управление SSH-ключом пользователя не реализовано на backend в этой сессии — раздел
              15.1 ТЗ упоминает его как часть профиля, но провижининг ОС-пользователей и связанных
              ключей вынесен за периметр проекта (см. docs/implementation_plan.md).
            </div>
          </Card>

          <ActiveSessionsCard />

          <Button variant="secondary" className="self-start" onClick={logout}>
            <LogOut className="size-4" />
            Выйти
          </Button>
        </div>
      </div>
    </div>
  );
}
