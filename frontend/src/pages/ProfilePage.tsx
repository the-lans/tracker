import { PageHeader } from "@/components/layout/PageHeader";
import { ActiveSessionsCard } from "@/components/profile/ActiveSessionsCard";
import { LogoutActions } from "@/components/profile/LogoutActions";
import { SshKeyCard } from "@/components/profile/SshKeyCard";
import { SftpConnectionCard } from "@/components/profile/SftpConnectionCard";
import { GoogleCalendarCard } from "@/components/profile/GoogleCalendarCard";
import { JiraConnectionCard } from "@/components/profile/JiraConnectionCard";
import { LlmCompactSwitchCard } from "@/components/profile/LlmCompactSwitchCard";
import { LlmThresholdsCard } from "@/components/profile/LlmThresholdsCard";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";
import { USER_ROLE_LABEL } from "@/lib/labels";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";
import { UserAvatar } from "@/components/common/avatar/UserAvatar";

export function ProfilePage() {
  const { user } = useAuth();
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

          <JiraConnectionCard />

          <GoogleCalendarCard />

          <LlmThresholdsCard />

          <LlmCompactSwitchCard />

          <ActiveSessionsCard />

          <LogoutActions />
        </div>
      </div>
    </div>
  );
}
