import { useState } from "react";
import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useNodeRuns } from "@/hooks/useAdmin";
import { formatDateTime } from "@/lib/utils";
import { NodeLogStatus } from "@/lib/types";
import { NODE_LOG_STATUS_LABEL, NODE_LOG_STATUS_TONE, NODE_LOG_TRIGGER_LABEL } from "@/lib/labels";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { SectionTitle } from "@/components/common/typography/SectionTitle";


/** Раздел 13.4: какая нода, в какой задаче, когда и с каким итоговым статусом. */
export function NodeRunsSection() {
  const [status, setStatus] = useState<NodeLogStatus | "all">("all");
  const { data: runs, isLoading } = useNodeRuns({ status: status === "all" ? undefined : status });

  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <SectionTitle>Выполнение нод</SectionTitle>
        <Select value={status} onValueChange={(value) => setStatus(value as NodeLogStatus | "all")}>
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все статусы</SelectItem>
            {Object.values(NodeLogStatus).map((value) => (
              <SelectItem key={value} value={value}>
                {NODE_LOG_STATUS_LABEL[value]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {isLoading && <LoadingState />}
      {(runs ?? []).map((run) => (
        <Card key={run.node_log_id} className="flex items-center gap-3 py-2.5">
          <Badge tone={NODE_LOG_STATUS_TONE[run.status]} className="shrink-0">{NODE_LOG_STATUS_LABEL[run.status]}</Badge>
          <div className="min-w-0 flex-1">
            <div className="truncate text-body font-bold" title={run.node_name ?? NODE_LOG_TRIGGER_LABEL[run.trigger_type]}>
              {run.node_name ?? NODE_LOG_TRIGGER_LABEL[run.trigger_type]}
              {run.attempt_number > 1 && ` · попытка ${run.attempt_number}`}
            </div>
            <div className="mt-0.5 text-caption text-text-3">
              {NODE_LOG_TRIGGER_LABEL[run.trigger_type]} · {formatDateTime(run.started_at)}
            </div>
          </div>
          <Link to={`/tasks/${run.task_id}`} className="touch-target inline-flex shrink-0 items-center justify-end font-mono text-small font-bold text-accent">
            {run.task_code}
          </Link>
        </Card>
      ))}
      {!isLoading && (runs ?? []).length === 0 && (
        <EmptyState
          compact
          title="Запусков нод пока нет"
          hint="Здесь появятся запуски нод по всем задачам. Если выбран статус — попробуйте «Все статусы»."
        />
      )}
    </section>
  );
}
