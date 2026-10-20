import { AppLogsSection } from "@/components/admin/AppLogsSection";
import { CeleryTasksSection } from "@/components/admin/CeleryTasksSection";
import { NodeRunsSection } from "@/components/admin/NodeRunsSection";

/** Раздел 13.4, 15.5: активные Celery-задачи, сводка выполнения нод, `app_logs`. */
export function MonitoringPanel() {
  return (
    <div className="flex flex-col gap-6">
      <CeleryTasksSection />
      <NodeRunsSection />
      <AppLogsSection />
    </div>
  );
}
