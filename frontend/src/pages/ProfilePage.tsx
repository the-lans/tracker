import { PageTabs, type PageTab } from "@/components/common/navigation/PageTabs";
import { PageHeader } from "@/components/layout/PageHeader";
import { ActiveSessionsCard } from "@/components/profile/ActiveSessionsCard";
import { LogoutActions } from "@/components/profile/LogoutActions";
import { SshKeyCard } from "@/components/profile/SshKeyCard";
import { SftpConnectionCard } from "@/components/profile/SftpConnectionCard";
import { GoogleCalendarCard } from "@/components/profile/GoogleCalendarCard";
import { JiraConnectionCard } from "@/components/profile/JiraConnectionCard";
import { TwgConnectionCard } from "@/components/profile/TwgConnectionCard";
import { LlmCompactSwitchCard } from "@/components/profile/LlmCompactSwitchCard";
import { CiAgentModelCard } from "@/components/profile/CiAgentModelCard";
import { LlmThresholdsCard } from "@/components/profile/LlmThresholdsCard";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";
import { USER_ROLE_LABEL } from "@/lib/labels";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";
import { UserAvatar } from "@/components/common/avatar/UserAvatar";

export function ProfilePage() {
  const { user } = useAuth();
  if (!user) return null;

  const tabs: PageTab[] = [
    {
      value: "account",
      label: "Аккаунт и безопасность",
      content: (
        <div className="flex max-w-lg flex-col gap-4">
          <Card className="flex min-w-0 items-center gap-3.5">
            <UserAvatar email={user.email} size="lg" />
            <div className="min-w-0">
              <div className="break-words font-bold">{user.email}</div>
              <div className="text-small text-text-3">{USER_ROLE_LABEL[user.role]}</div>
            </div>
          </Card>
          <ActiveSessionsCard />
          <LogoutActions />
        </div>
      ),
    },
    {
      value: "connections",
      label: "Подключения",
      content: (
        <div className="flex max-w-lg flex-col gap-4">
          <JiraConnectionCard />
          <TwgConnectionCard />
          <GoogleCalendarCard />
        </div>
      ),
    },
    {
      value: "files",
      label: "Доступ к файлам",
      content: (
        <div className="flex max-w-lg flex-col gap-4">
          <SshKeyCard />
          <SftpConnectionCard />
        </div>
      ),
    },
    {
      value: "agent",
      label: "Настройки агента",
      content: (
        <div className="flex max-w-lg flex-col gap-4">
          <LlmThresholdsCard />
          <LlmCompactSwitchCard />
          <CiAgentModelCard />
        </div>
      ),
    },
  ];

  return (
    <div className={PAGE_ROOT}>
      <PageHeader title="Профиль" />
      <div className={PAGE_BODY}>
        <PageTabs tabs={tabs} />
      </div>
    </div>
  );
}
