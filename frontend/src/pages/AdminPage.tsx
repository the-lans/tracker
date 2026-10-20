import { PageHeader } from "@/components/layout/PageHeader";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { UsersPanel } from "@/components/admin/UsersPanel";
import { SystemSettingsPanel } from "@/components/admin/SystemSettingsPanel";
import { McpServersPanel } from "@/components/admin/McpServersPanel";
import { PeriodicTasksPanel } from "@/components/admin/PeriodicTasksPanel";
import { MonitoringPanel } from "@/components/admin/MonitoringPanel";
import { PromptLibraryPanel } from "@/components/admin/PromptLibraryPanel";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";

export function AdminPage() {
  return (
    <div className={PAGE_ROOT}>
      <PageHeader title="Администрирование" />
      <div className={PAGE_BODY}>
        <Tabs defaultValue="users">
          <TabsList className="mb-4 flex-wrap">
            <TabsTrigger value="users">Пользователи и доступ</TabsTrigger>
            <TabsTrigger value="settings">Системные настройки</TabsTrigger>
            <TabsTrigger value="mcp">MCP-серверы</TabsTrigger>
            <TabsTrigger value="periodic">Периодические задачи</TabsTrigger>
            <TabsTrigger value="monitoring">Мониторинг</TabsTrigger>
            <TabsTrigger value="library">Библиотека промтов</TabsTrigger>
          </TabsList>
          <TabsContent value="users">
            <UsersPanel />
          </TabsContent>
          <TabsContent value="settings">
            <SystemSettingsPanel />
          </TabsContent>
          <TabsContent value="mcp">
            <McpServersPanel />
          </TabsContent>
          <TabsContent value="periodic">
            <PeriodicTasksPanel />
          </TabsContent>
          <TabsContent value="monitoring">
            <MonitoringPanel />
          </TabsContent>
          <TabsContent value="library">
            <PromptLibraryPanel />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
