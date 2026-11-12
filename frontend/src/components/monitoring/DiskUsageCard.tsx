import { MonitoringCard } from "@/components/monitoring/MonitoringCard";
import { useDiskUsage } from "@/hooks/useMonitoring";
import { VOLUME_LABEL } from "@/lib/labels";
import type { DiskUsage } from "@/lib/monitoring.types";
import { cn, formatFileSize, formatRelativeShort } from "@/lib/utils";

/** Свободного места меньше этой доли — предупреждение. */
const LOW_FREE_SPACE_RATIO = 0.1;

function sizeOrDash(bytes: number | null): string {
  return bytes === null ? "—" : formatFileSize(bytes);
}

function FreeSpace({ usage }: { usage: DiskUsage }) {
  if (usage.free_bytes === null || usage.total_bytes === null) {
    return <span className="text-text-3">неизвестно</span>;
  }
  const low = usage.total_bytes > 0 && usage.free_bytes / usage.total_bytes < LOW_FREE_SPACE_RATIO;
  return (
    <span className={cn("font-bold tabular-nums", low ? "text-danger-text" : "text-text")}>
      {formatFileSize(usage.free_bytes)} из {formatFileSize(usage.total_bytes)}
    </span>
  );
}

/** Раздел 15.5: размеры volume по последнему замеру, база данных и свободное место. */
export function DiskUsageCard() {
  const { data, isLoading, isError } = useDiskUsage();

  return (
    <MonitoringCard title="Место на диске" isLoading={isLoading} isError={isError}>
      {data && (
        <div className="flex flex-col gap-3">
          <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5 text-body">
            {data.volumes.map((volume) => (
              <div key={volume.name} className="contents">
                <dt className="min-w-0 truncate text-text-2">{VOLUME_LABEL[volume.name]}</dt>
                <dd className="text-right tabular-nums">{sizeOrDash(volume.size_bytes)}</dd>
              </div>
            ))}
            <dt className="text-text-2">База данных</dt>
            <dd className="text-right tabular-nums">{formatFileSize(data.database_bytes)}</dd>
          </dl>
          {data.measured_at ? (
            <div className="text-caption text-text-3">Замер: {formatRelativeShort(data.measured_at)}</div>
          ) : (
            <div className="text-caption text-text-3">
              Размеры каталогов ещё не замерены — их считает периодическая задача «Замер места на
              диске».
            </div>
          )}
          <div className="border-t border-border pt-3 text-body">
            <span className="text-text-3">Свободно: </span>
            <FreeSpace usage={data} />
          </div>
        </div>
      )}
    </MonitoringCard>
  );
}
