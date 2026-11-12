import { BackupStatus } from "@/components/admin/BackupStatus";
import { ContainersCard } from "@/components/monitoring/ContainersCard";
import { DiskUsageCard } from "@/components/monitoring/DiskUsageCard";
import { LlmUsageCard } from "@/components/monitoring/LlmUsageCard";
import { MonitoringCard } from "@/components/monitoring/MonitoringCard";
import { NodeStatsCard } from "@/components/monitoring/NodeStatsCard";
import { QueuesCard } from "@/components/monitoring/QueuesCard";
import { ServerStatusCard } from "@/components/monitoring/ServerStatusCard";
import { useServerOverview } from "@/hooks/useMonitoring";

/** Раздел 15.5: вкладка «Обзор» — состояние сервера и сводные показатели. */
export function MonitoringOverview() {
  const { data: overview, isLoading, isError } = useServerOverview();

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <MonitoringCard title="Состояние сервера" isLoading={isLoading} isError={isError}>
        {overview && <ServerStatusCard overview={overview} />}
      </MonitoringCard>
      <MonitoringCard title="Очереди" isLoading={isLoading} isError={isError}>
        {overview && <QueuesCard overview={overview} />}
      </MonitoringCard>
      <NodeStatsCard />
      <MonitoringCard title="Резервные копии" isLoading={isLoading} isError={isError}>
        {overview && (
          <BackupStatus lastBackup={overview.last_backup} lastVerify={overview.last_verify} />
        )}
      </MonitoringCard>
      <LlmUsageCard />
      <DiskUsageCard />
      <ContainersCard className="lg:col-span-2" />
    </div>
  );
}
