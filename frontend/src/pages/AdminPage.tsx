import { GitCredentialsPanel } from "@/components/admin/GitCredentialsPanel";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageTabs, type PageTab } from "@/components/common/navigation/PageTabs";
import { UsersPanel } from "@/components/admin/UsersPanel";
import { SystemSettingsPanel } from "@/components/admin/SystemSettingsPanel";
import { McpServersPanel } from "@/components/admin/McpServersPanel";
import { LlmProxyPanel } from "@/components/admin/LlmProxyPanel";
import { PeriodicTasksPanel } from "@/components/admin/PeriodicTasksPanel";
import { PromptLibraryPanel } from "@/components/admin/PromptLibraryPanel";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";

const ADMIN_TABS: PageTab[] = [
  { value: "users", label: "Пользователи и доступ", content: <UsersPanel /> },
  { value: "settings", label: "Системные настройки", content: <SystemSettingsPanel /> },
  { value: "git-access", label: "Учётные данные Git", content: <GitCredentialsPanel /> },
  { value: "mcp", label: "MCP-серверы", content: <McpServersPanel /> },
  { value: "llm-proxy", label: "LLM-прокси", content: <LlmProxyPanel /> },
  { value: "periodic", label: "Периодические задачи", content: <PeriodicTasksPanel /> },
  { value: "library", label: "Библиотека промтов", content: <PromptLibraryPanel /> },
];

export function AdminPage() {
  return (
    <div className={PAGE_ROOT}>
      <PageHeader title="Администрирование" />
      <div className={PAGE_BODY}>
        <PageTabs tabs={ADMIN_TABS} />
      </div>
    </div>
  );
}
