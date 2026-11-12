import { useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AppLogsSection } from "@/components/monitoring/AppLogsSection";
import { CeleryTasksSection } from "@/components/monitoring/CeleryTasksSection";
import { MonitoringOverview } from "@/components/monitoring/MonitoringOverview";
import { NodeRunsSection } from "@/components/monitoring/NodeRunsSection";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";

const MONITORING_TABS = {
  overview: "Обзор",
  celery: "Активные Celery-задачи",
  "node-runs": "Выполнение нод",
  "app-logs": "App logs",
} as const;
type MonitoringTab = keyof typeof MONITORING_TABS;
const DEFAULT_TAB: MonitoringTab = "overview";
const TAB_PARAM = "tab";

function isMonitoringTab(value: string | null): value is MonitoringTab {
  return value !== null && value in MONITORING_TABS;
}

/** Раздел 15.5: «Мониторинг» — отдельная страница администратора; вкладка — в адресе. */
export function MonitoringPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get(TAB_PARAM);
  const tab = isMonitoringTab(requested) ? requested : DEFAULT_TAB;

  return (
    <div className={PAGE_ROOT}>
      <PageHeader title="Мониторинг" />
      <div className={PAGE_BODY}>
        <Tabs
          value={tab}
          onValueChange={(value) => setSearchParams({ [TAB_PARAM]: value }, { replace: true })}
        >
          <TabsList className="mb-4 flex-wrap">
            {Object.entries(MONITORING_TABS).map(([value, label]) => (
              <TabsTrigger key={value} value={value}>
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
          <TabsContent value="overview">
            <MonitoringOverview />
          </TabsContent>
          <TabsContent value="celery">
            <CeleryTasksSection />
          </TabsContent>
          <TabsContent value="node-runs">
            <NodeRunsSection />
          </TabsContent>
          <TabsContent value="app-logs">
            <AppLogsSection />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
