import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { MonitoringCard } from "@/components/monitoring/MonitoringCard";
import { useTaskContainers } from "@/hooks/useMonitoring";
import { CONTAINER_KIND_LABEL } from "@/lib/labels";
import { ContainerKind, type TaskContainer } from "@/lib/monitoring.types";
import { formatRelativeShort } from "@/lib/utils";

function TaskReference({ container }: { container: TaskContainer }) {
  const label = container.task_code ?? container.task_id?.slice(0, 8);
  if (!label) return null;
  if (!container.task_id) return <span className="font-mono text-small font-bold">{label}</span>;
  return (
    <Link
      to={`/tasks/${container.task_id}`}
      className="touch-target inline-flex items-center font-mono text-small font-bold text-accent"
    >
      {label}
    </Link>
  );
}

/**
 * Раздел 15.5, 16.2: контейнеры сессий и script-нод. «Осиротевший» —
 * по тем же правилам, что у уборки: нода пережила свой дедлайн, у сессии нет
 * воркера; периодическая уборка остановит его сама.
 */
export function ContainersCard({ className }: { className?: string }) {
  const { data, isLoading, isError } = useTaskContainers();
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
            <li key={container.name} className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <Badge tone={container.kind === ContainerKind.SESSION ? "info" : "neutral"}>
                {CONTAINER_KIND_LABEL[container.kind]}
              </Badge>
              <TaskReference container={container} />
              {container.orphaned && <Badge tone="danger">осиротел</Badge>}
              <span className="min-w-0 flex-1 truncate font-mono text-caption text-text-3" title={container.name}>
                {container.name}
              </span>
              <span className="shrink-0 text-caption text-text-3">
                {formatRelativeShort(container.started_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </MonitoringCard>
  );
}
