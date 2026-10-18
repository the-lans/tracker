import { PageHeader } from "@/components/layout/PageHeader";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { UsersPanel } from "@/components/admin/UsersPanel";
import { SystemSettingsPanel } from "@/components/admin/SystemSettingsPanel";
import { McpServersPanel } from "@/components/admin/McpServersPanel";
import { PeriodicTasksPanel } from "@/components/admin/PeriodicTasksPanel";
import { MonitoringPanel } from "@/components/admin/MonitoringPanel";
import { PromptLibraryPanel } from "@/components/admin/PromptLibraryPanel";

export function AdminPage() {
  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Администрирование" />
      <div className="min-h-0 flex-1 overflow-auto px-5 pb-8 lg:px-8">
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
