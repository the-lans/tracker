import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
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

export function MonitoringPanel() {
  const [level, setLevel] = useState<AppLogLevel | "all">("all");
  const { data: logs, isLoading } = useAppLogs({ level: level === "all" ? undefined : level });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="text-[12.5px] font-extrabold text-text-2">app_logs</div>
        <Select value={level} onValueChange={(v) => setLevel(v as AppLogLevel | "all")}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все уровни</SelectItem>
            <SelectItem value={AppLogLevel.CRITICAL}>critical</SelectItem>
            <SelectItem value={AppLogLevel.ERROR}>error</SelectItem>
            <SelectItem value={AppLogLevel.WARNING}>warning</SelectItem>
            <SelectItem value={AppLogLevel.INFO}>info</SelectItem>
            <SelectItem value={AppLogLevel.DEBUG}>debug</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="rounded-md border border-warning-border bg-warning-tint px-3 py-2 text-[12px] text-warning-text">
        Список активных Celery-задач по всем пользователям (вторая половина раздела 15.5
        «Мониторинг») не отдаётся ни одним эндпоинтом API — показан только просмотр `app_logs`.
      </div>
      {isLoading && <div className="text-text-3">Загрузка…</div>}
      <div className="flex flex-col gap-1.5">
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
      </div>
    </div>
  );
}
