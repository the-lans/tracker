import { useState, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { NodeOutputSheet } from "@/components/tasks/NodeOutputSheet";
import { STATUS_LABEL, STATUS_TONE, TRIGGER_LABEL } from "@/components/tasks/nodeLogLabels";
import { useFilteredNodeLogs, useTaskNodes } from "@/hooks/useTasks";
import { formatDateTime } from "@/lib/utils";
import { NodeLogStatus, NodeLogTriggerType, type NodeLog } from "@/lib/types";

const ALL = "all";

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="w-44" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{label}: все</SelectItem>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Раздел 13.4: история выполнения с фильтрами; строка открывает полный вывод. */
export function TaskLogsPanel({ taskId, header }: { taskId: string; header: ReactNode }) {
  const [nodeId, setNodeId] = useState(ALL);
  const [status, setStatus] = useState(ALL);
  const [triggerType, setTriggerType] = useState(ALL);
  const [selected, setSelected] = useState<NodeLog | null>(null);
  const { data: taskNodes } = useTaskNodes(taskId, true);
  const { data: logs, isLoading } = useFilteredNodeLogs(taskId, {
    nodeId: nodeId === ALL ? undefined : nodeId,
    status: status === ALL ? undefined : (status as NodeLogStatus),
    triggerType: triggerType === ALL ? undefined : (triggerType as NodeLogTriggerType),
  });
  const nodeNames = new Map((taskNodes ?? []).map((node) => [node.node_id, node.name]));
  const titleOf = (log: NodeLog) =>
    (log.node_id && nodeNames.get(log.node_id)) || TRIGGER_LABEL[log.trigger_type];

  return (
    <div className="flex min-w-0 flex-1 flex-col bg-[#fdfdfe]">
      <div className="flex items-center justify-between border-b border-border px-6 py-3.5">
        {header}
      </div>
      <div className="flex flex-wrap gap-2 border-b border-border px-6 py-3">
        <FilterSelect
          label="Нода"
          value={nodeId}
          onChange={setNodeId}
          options={(taskNodes ?? []).map((node) => ({ value: node.node_id, label: node.name }))}
        />
        <FilterSelect
          label="Статус"
          value={status}
          onChange={setStatus}
          options={Object.values(NodeLogStatus).map((value) => ({ value, label: STATUS_LABEL[value] }))}
        />
        <FilterSelect
          label="Источник"
          value={triggerType}
          onChange={setTriggerType}
          options={Object.values(NodeLogTriggerType).map((value) => ({
            value,
            label: TRIGGER_LABEL[value],
          }))}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-6 py-3">
        {isLoading && <div className="text-text-3">Загрузка…</div>}
        {!isLoading && (logs ?? []).length === 0 && (
          <div className="py-6 text-center text-[13px] text-text-3">Записей нет</div>
        )}
        <div className="flex flex-col">
          {(logs ?? []).map((log) => (
            <button
              key={log.id}
              type="button"
              onClick={() => setSelected(log)}
              className="flex touch-target items-center gap-3 border-t border-border py-2 text-left first:border-t-0 hover:bg-surface-2"
            >
              <Badge tone={STATUS_TONE[log.status]}>{STATUS_LABEL[log.status]}</Badge>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[12.5px] font-bold">{titleOf(log)}</div>
                <div className="text-[11px] text-text-3">
                  {TRIGGER_LABEL[log.trigger_type]} · попытка {log.attempt_number} ·{" "}
                  {formatDateTime(log.started_at)}
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>
      {selected && (
        <NodeOutputSheet
          log={selected}
          title={titleOf(selected)}
          open
          onOpenChange={(open) => !open && setSelected(null)}
        />
      )}
    </div>
  );
}
