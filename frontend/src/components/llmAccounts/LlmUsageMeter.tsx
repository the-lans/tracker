import { cn, formatDateTime } from "@/lib/utils";

/** Раздел 15.1: расход окна лимита в процентах и время его сброса; null — расход неизвестен. */
export function LlmUsageMeter({
  label,
  pct,
  resetsAt,
  threshold,
}: {
  label: string;
  pct: string | null;
  resetsAt: string | null;
  /** Порог переключения пользователя: расход на пороге и выше выделяется. */
  threshold?: number;
}) {
  const value = pct === null ? null : Number(pct);
  const above = value !== null && threshold !== undefined && value >= threshold;
  return (
    <div className="flex min-w-0 flex-col gap-0.5" aria-label={`${label}: ${value === null ? "неизвестно" : `${value}%`}`}>
      <div className="flex items-baseline justify-between gap-2 text-meta">
        <span className="text-text-3">{label}</span>
        <span className={cn("font-bold", above ? "text-warning-text" : "text-text")}>
          {value === null ? "—" : `${value}%`}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
        <div
          className={cn("h-full rounded-full", above ? "bg-warning" : "bg-accent")}
          style={{ width: `${Math.min(100, value ?? 0)}%` }}
        />
      </div>
      {resetsAt && <span className="text-caption text-text-3">сброс {formatDateTime(resetsAt)}</span>}
    </div>
  );
}
