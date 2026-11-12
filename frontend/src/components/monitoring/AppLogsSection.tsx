import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAppLogs } from "@/hooks/useAdmin";
import { formatDateTime } from "@/lib/utils";
import { AppLogLevel } from "@/lib/types";
import { APP_LOG_LEVEL_LABEL, APP_LOG_LEVEL_TONE } from "@/lib/labels";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { SectionTitle } from "@/components/common/typography/SectionTitle";

/** Граница дня `<input type="date">` в локальной зоне — в ISO для API. */
function dayBoundary(value: string, endOfDay: boolean): string | undefined {
  if (!value) return undefined;
  const date = new Date(`${value}T00:00:00`);
  if (endOfDay) date.setDate(date.getDate() + 1);
  return date.toISOString();
}

/** Раздел 15.5, 17.2: `app_logs` с фильтрами по уровню, источнику, задаче и дате. */
export function AppLogsSection() {
  const [level, setLevel] = useState<AppLogLevel | "all">("all");
  const [source, setSource] = useState("");
  const [taskCode, setTaskCode] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const { data: logs, isLoading } = useAppLogs({
    level: level === "all" ? undefined : level,
    source: source.trim() || undefined,
    taskCode: taskCode.trim() || undefined,
    createdFrom: dayBoundary(dateFrom, false),
    createdTo: dayBoundary(dateTo, true),
  });

  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SectionTitle>app_logs</SectionTitle>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label="Источник"
            placeholder="Источник"
            className="w-40"
            value={source}
            onChange={(event) => setSource(event.target.value)}
          />
          <Input
            aria-label="Задача"
            placeholder="Задача (RR-…)"
            className="w-40"
            value={taskCode}
            onChange={(event) => setTaskCode(event.target.value)}
          />
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
                  {APP_LOG_LEVEL_LABEL[value]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {isLoading && <LoadingState />}
      {(logs ?? []).map((log) => (
        <Card key={log.id} className="flex items-start gap-3 py-2.5">
          <Badge tone={APP_LOG_LEVEL_TONE[log.level]} className="mt-0.5">
            {APP_LOG_LEVEL_LABEL[log.level]}
          </Badge>
          <div className="min-w-0 flex-1">
            <div className="text-body [overflow-wrap:anywhere]">{log.message}</div>
            <div className="mt-0.5 text-caption text-text-3">
              {log.source} · {formatDateTime(log.created_at)}
              {log.task_id && ` · task ${log.task_id.slice(0, 8)}`}
            </div>
          </div>
        </Card>
      ))}
      {!isLoading && (logs ?? []).length === 0 && (
        <EmptyState
          compact
          title="Записей в журнале нет"
          hint="Измените уровень, источник, задачу или диапазон дат в фильтрах выше."
        />
      )}
    </section>
  );
}
