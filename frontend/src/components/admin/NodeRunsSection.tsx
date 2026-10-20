import { useState } from "react";
import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useNodeRuns } from "@/hooks/useAdmin";
import { formatDateTime } from "@/lib/utils";
import { NodeLogStatus } from "@/lib/types";

const STATUS_TONE: Record<NodeLogStatus, "danger" | "warning" | "info" | "success" | "neutral"> = {
  [NodeLogStatus.PENDING]: "neutral",
  [NodeLogStatus.RUNNING]: "info",
  [NodeLogStatus.AWAITING_DECISION]: "warning",
  [NodeLogStatus.SUCCESS]: "success",
  [NodeLogStatus.FAILED]: "danger",
  [NodeLogStatus.STOPPED]: "warning",
};

/** Раздел 13.4: какая нода, в какой задаче, когда и с каким итоговым статусом. */
export function NodeRunsSection() {
  const [status, setStatus] = useState<NodeLogStatus | "all">("all");
  const { data: runs, isLoading } = useNodeRuns({ status: status === "all" ? undefined : status });

  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div className="text-[12.5px] font-extrabold text-text-2">Выполнение нод</div>
        <Select value={status} onValueChange={(value) => setStatus(value as NodeLogStatus | "all")}>
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все статусы</SelectItem>
            {Object.values(NodeLogStatus).map((value) => (
              <SelectItem key={value} value={value}>
                {value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {isLoading && <div className="text-text-3">Загрузка…</div>}
      {(runs ?? []).map((run) => (
        <Card key={run.node_log_id} className="flex items-center gap-3 py-2.5">
          <Badge tone={STATUS_TONE[run.status]}>{run.status}</Badge>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13px] font-bold">
              {run.node_name ?? run.trigger_type}
              {run.attempt_number > 1 && ` · попытка ${run.attempt_number}`}
            </div>
            <div className="mt-0.5 text-[11px] text-text-3">
              {run.trigger_type} · {formatDateTime(run.started_at)}
            </div>
          </div>
          <Link to={`/tasks/${run.task_id}`} className="font-mono text-[12px] font-bold text-accent">
            {run.task_code}
          </Link>
        </Card>
      ))}
      {!isLoading && (runs ?? []).length === 0 && (
        <div className="py-3 text-center text-text-3">Нет записей</div>
      )}
    </section>
  );
}
