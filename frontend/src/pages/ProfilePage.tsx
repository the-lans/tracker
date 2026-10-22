import { LogOut } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { ActiveSessionsCard } from "@/components/profile/ActiveSessionsCard";
import { SshKeyCard } from "@/components/profile/SshKeyCard";
import { SftpConnectionCard } from "@/components/profile/SftpConnectionCard";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/stores/authStore";
import { USER_ROLE_LABEL } from "@/lib/labels";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";
import { UserAvatar } from "@/components/common/avatar/UserAvatar";

export function ProfilePage() {
  const { user, logout } = useAuth();
  if (!user) return null;

  return (
    <div className={PAGE_ROOT}>
      <PageHeader title="Профиль" />
      <div className={PAGE_BODY}>
        <div className="flex max-w-lg flex-col gap-4">
          <Card className="flex items-center gap-3.5">
            <UserAvatar email={user.email} size="lg" />
            <div>
              <div className="font-bold">{user.email}</div>
              <div className="text-small text-text-3">{USER_ROLE_LABEL[user.role]}</div>
            </div>
          </Card>

          <SshKeyCard />

          <SftpConnectionCard />

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
