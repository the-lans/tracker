import { PageHeader } from "@/components/layout/PageHeader";
import { PageTabs, type PageTab } from "@/components/common/navigation/PageTabs";
import { AppLogsSection } from "@/components/monitoring/AppLogsSection";
import { CeleryTasksSection } from "@/components/monitoring/CeleryTasksSection";
import { MonitoringOverview } from "@/components/monitoring/MonitoringOverview";
import { NodeRunsSection } from "@/components/monitoring/NodeRunsSection";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";

const MONITORING_TABS: PageTab[] = [
  { value: "overview", label: "Обзор", content: <MonitoringOverview /> },
  { value: "celery", label: "Активные Celery-задачи", content: <CeleryTasksSection /> },
  { value: "node-runs", label: "Выполнение нод", content: <NodeRunsSection /> },
  { value: "app-logs", label: "App logs", content: <AppLogsSection /> },
];

/** Раздел 15.5: «Мониторинг» — отдельная страница администратора; вкладка — в адресе. */
export function MonitoringPage() {
  return (
    <div className={PAGE_ROOT}>
      <PageHeader title="Мониторинг" />
      <div className={PAGE_BODY}>
        <PageTabs tabs={MONITORING_TABS} />
      </div>
    </div>
  );
}
