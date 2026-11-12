import { useState } from "react";
import { SegmentedControl } from "@/components/common/navigation/SegmentedControl";
import { MonitoringCard } from "@/components/monitoring/MonitoringCard";
import { StatTile } from "@/components/monitoring/StatTile";
import { useNodeStats } from "@/hooks/useMonitoring";
import { STATS_PERIOD_LABEL } from "@/lib/labels";
import { StatsPeriod, type NodeStats } from "@/lib/monitoring.types";
import { cn, formatDuration } from "@/lib/utils";
import { CARD_DIVIDER } from "@/styles/classes";

function durationOrDash(seconds: number | null): string {
  return seconds === null ? "—" : formatDuration(seconds);
}

function NodeStatsBody({ stats }: { stats: NodeStats }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <StatTile label="Запусков" value={stats.total} />
        <StatTile label="Успешно" value={stats.success} tone="success" />
        <StatTile label="С ошибкой" value={stats.failed} tone={stats.failed > 0 ? "danger" : "default"} />
        <StatTile label="Остановлено" value={stats.stopped} />
        <StatTile label="Повторы" value={stats.retries} tone={stats.retries > 0 ? "warning" : "default"} />
        <StatTile
          label="Среднее / макс."
          value={`${durationOrDash(stats.avg_duration_seconds)} / ${durationOrDash(stats.max_duration_seconds)}`}
        />
      </div>
      <div className="text-caption text-text-3">
        Длительность — без запусков, ждавших решения пользователя.
      </div>
      <div className={cn("flex flex-col gap-1.5", CARD_DIVIDER)}>
        <div className="text-note font-bold text-text-2">Чаще всего падают</div>
        {stats.top_failing.length === 0 ? (
          <div className="text-body text-text-3">Упавших нод нет</div>
        ) : (
          <ol className="flex flex-col gap-1">
            {stats.top_failing.map((node) => (
              <li key={node.node_id} className="flex min-w-0 items-center gap-2 text-body">
                <span className="min-w-0 flex-1 truncate" title={node.node_name}>
                  {node.node_name}
                </span>
                <span className="shrink-0 font-bold tabular-nums text-danger-text">{node.failed}</span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

/** Раздел 15.5: итоги запусков нод за 24 часа или 7 дней. */
export function NodeStatsCard() {
  const [period, setPeriod] = useState<StatsPeriod>(StatsPeriod.DAY);
  const { data, isLoading, isError } = useNodeStats(period);

  return (
    <MonitoringCard
      title="Статистика нод"
      isLoading={isLoading}
      isError={isError}
      action={
        <SegmentedControl value={period} options={STATS_PERIOD_LABEL} onChange={setPeriod} label="Период" />
      }
    >
      {data && <NodeStatsBody stats={data} />}
    </MonitoringCard>
  );
}
