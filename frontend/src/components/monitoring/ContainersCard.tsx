import { Badge } from "@/components/ui/badge";
import { MonitoringCard } from "@/components/monitoring/MonitoringCard";
import { TaskCodeLink } from "@/components/tasks/TaskCodeLink";
import { useTaskContainers } from "@/hooks/useMonitoring";
import { CONTAINER_KIND_LABEL } from "@/lib/labels";
import { ContainerKind } from "@/lib/monitoring.types";
import { formatRelativeShort } from "@/lib/utils";
import { WRAP_ROW } from "@/styles/classes";

/**
 * Раздел 15.5, 16.2: контейнеры сессий и script-нод. «Осиротевший» —
 * по тем же правилам, что у уборки: нода пережила свой дедлайн, у сессии нет
 * воркера; периодическая уборка остановит его сама.
 */
export function ContainersCard({ className }: { className?: string }) {
  // Время — от последнего опроса: без этого строка не перерисуется, пока
  // список контейнеров не изменится.
  const { data, isLoading, isError, dataUpdatedAt } = useTaskContainers();
  const orphaned = (data ?? []).filter((container) => container.orphaned).length;

  return (
    <MonitoringCard
      title="Контейнеры задач"
      className={className}
      isLoading={isLoading}
      isError={isError}
      action={orphaned > 0 && <Badge tone="danger">осиротевших: {orphaned}</Badge>}
    >
      {data && data.length === 0 && <div className="text-body text-text-3">Контейнеров задач нет</div>}
      {data && data.length > 0 && (
        <ul className="flex flex-col gap-2">
          {data.map((container) => (
            <li key={container.name} className={WRAP_ROW}>
              <Badge tone={container.kind === ContainerKind.SESSION ? "info" : "neutral"}>
                {CONTAINER_KIND_LABEL[container.kind]}
              </Badge>
              <TaskCodeLink taskId={container.task_id} code={container.task_code} />
              {container.orphaned && <Badge tone="danger">осиротел</Badge>}
              <span className="min-w-0 flex-1 truncate font-mono text-caption text-text-3" title={container.name}>
                {container.name}
              </span>
              <span className="shrink-0 text-caption text-text-3">
                {formatRelativeShort(container.started_at, dataUpdatedAt)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </MonitoringCard>
  );
}
