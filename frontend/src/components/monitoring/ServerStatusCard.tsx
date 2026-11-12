import { Badge } from "@/components/ui/badge";
import { SERVER_DEPENDENCY_LABEL } from "@/lib/labels";
import type { ServerOverview } from "@/lib/monitoring.types";
import { formatDateTime } from "@/lib/utils";

const SHORT_SHA_LENGTH = 7;

function MaintenanceBadge({ maintenance }: { maintenance: boolean | null }) {
  if (maintenance === null) return <Badge>неизвестно</Badge>;
  return maintenance ? <Badge tone="warning">идёт обновление</Badge> : <Badge tone="success">нет</Badge>;
}

/** Раздел 15.5: зависимости сервера, версия, время развёртывания и флаг обслуживания. */
export function ServerStatusCard({ overview }: { overview: ServerOverview }) {
  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col gap-2">
        {overview.dependencies.map((dependency) => (
          <li key={dependency.name} className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-bold text-text">{SERVER_DEPENDENCY_LABEL[dependency.name]}</span>
            <Badge tone={dependency.ok ? "success" : "danger"}>
              {dependency.ok ? "работает" : "недоступен"}
            </Badge>
            {dependency.error && (
              <span className="min-w-0 break-words text-small text-danger-text">{dependency.error}</span>
            )}
          </li>
        ))}
      </ul>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 border-t border-border pt-3 text-body">
        <dt className="text-text-3">Версия</dt>
        <dd className="min-w-0 truncate font-mono" title={overview.version}>
          {overview.version.slice(0, SHORT_SHA_LENGTH)}
        </dd>
        <dt className="text-text-3">Развёрнута</dt>
        <dd>{overview.deployed_at ? formatDateTime(overview.deployed_at) : "неизвестно"}</dd>
        <dt className="text-text-3">Обслуживание</dt>
        <dd>
          <MaintenanceBadge maintenance={overview.maintenance} />
        </dd>
      </dl>
    </div>
  );
}
