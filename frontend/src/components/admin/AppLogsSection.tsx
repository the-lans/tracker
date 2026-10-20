import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAppLogs } from "@/hooks/useAdmin";
import { formatDateTime } from "@/lib/utils";
import { AppLogLevel } from "@/lib/types";

const LEVEL_TONE: Record<AppLogLevel, "danger" | "warning" | "info" | "neutral"> = {
  [AppLogLevel.CRITICAL]: "danger",
  [AppLogLevel.ERROR]: "danger",
  [AppLogLevel.WARNING]: "warning",
  [AppLogLevel.INFO]: "info",
  [AppLogLevel.DEBUG]: "neutral",
};

/** Граница дня `<input type="date">` в локальной зоне — в ISO для API. */
function dayBoundary(value: string, endOfDay: boolean): string | undefined {
  if (!value) return undefined;
  const date = new Date(`${value}T00:00:00`);
  if (endOfDay) date.setDate(date.getDate() + 1);
  return date.toISOString();
}

/** Раздел 15.5: `app_logs` с фильтрами по уровню и дате. */
export function AppLogsSection() {
  const [level, setLevel] = useState<AppLogLevel | "all">("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const { data: logs, isLoading } = useAppLogs({
    level: level === "all" ? undefined : level,
    createdFrom: dayBoundary(dateFrom, false),
    createdTo: dayBoundary(dateTo, true),
  });

  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[12.5px] font-extrabold text-text-2">app_logs</div>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            type="date"
            aria-label="С даты"
            className="w-40"
            value={dateFrom}
            onChange={(event) => setDateFrom(event.target.value)}
          />
          <Input
            type="date"
            aria-label="По дату"
            className="w-40"
            value={dateTo}
            onChange={(event) => setDateTo(event.target.value)}
          />
          <Select value={level} onValueChange={(value) => setLevel(value as AppLogLevel | "all")}>
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все уровни</SelectItem>
              {Object.values(AppLogLevel).map((value) => (
                <SelectItem key={value} value={value}>
                  {value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {isLoading && <div className="text-text-3">Загрузка…</div>}
      {(logs ?? []).map((log) => (
        <Card key={log.id} className="flex items-start gap-3 py-2.5">
          <Badge tone={LEVEL_TONE[log.level]} className="mt-0.5">
            {log.level}
          </Badge>
          <div className="min-w-0 flex-1">
            <div className="text-[13px]">{log.message}</div>
            <div className="mt-0.5 text-[11px] text-text-3">
              {log.source} · {formatDateTime(log.created_at)}
              {log.task_id && ` · task ${log.task_id.slice(0, 8)}`}
            </div>
          </div>
        </Card>
      ))}
      {!isLoading && (logs ?? []).length === 0 && (
        <div className="py-6 text-center text-text-3">Нет записей</div>
      )}
    </section>
  );
}
