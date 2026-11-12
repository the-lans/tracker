import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useNodeRuns } from "@/hooks/useAdmin";
import { formatDateTime } from "@/lib/utils";
import { NodeLogStatus } from "@/lib/types";
import { NODE_LOG_STATUS_LABEL, NODE_LOG_STATUS_TONE, NODE_LOG_TRIGGER_LABEL } from "@/lib/labels";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { QueryState } from "@/components/common/feedback/QueryState";
import { FilterSelect } from "@/components/common/filters/FilterSelect";
import { SectionTitle } from "@/components/common/typography/SectionTitle";
import { TaskCodeLink } from "@/components/tasks/TaskCodeLink";

/** Раздел 13.4: какая нода, в какой задаче, когда и с каким итоговым статусом. */
export function NodeRunsSection() {
  const [status, setStatus] = useState<NodeLogStatus>();
  const { data: runs, isLoading, isError } = useNodeRuns({ status });

  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <SectionTitle>Выполнение нод</SectionTitle>
        <FilterSelect
          value={status}
          onChange={setStatus}
          values={Object.values(NodeLogStatus)}
          labels={NODE_LOG_STATUS_LABEL}
          allLabel="Все статусы"
          label="Статус"
          className="w-44"
        />
      </div>
      <QueryState isLoading={isLoading} isError={isError}>
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
            <TaskCodeLink taskId={run.task_id} code={run.task_code} className="shrink-0 justify-end" />
          </Card>
        ))}
        {(runs ?? []).length === 0 && (
          <EmptyState
            compact
            title="Запусков нод пока нет"
            hint="Здесь появятся запуски нод по всем задачам. Если выбран статус — попробуйте «Все статусы»."
          />
        )}
      </QueryState>
    </section>
  );
}
