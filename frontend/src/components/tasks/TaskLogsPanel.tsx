import { useState, type ReactNode } from "react";
import { ScrollText } from "lucide-react";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { NodeOutputSheet } from "@/components/tasks/NodeOutputSheet";
import { NODE_LOG_STATUS_LABEL, NODE_LOG_STATUS_TONE, NODE_LOG_TRIGGER_LABEL } from "@/lib/labels";
import { useFilteredNodeLogs, useTaskNodes } from "@/hooks/useTasks";
import { formatDateTime } from "@/lib/utils";
import { NodeLogStatus, NodeLogTriggerType, type NodeLog } from "@/lib/types";
import { LoadingState } from "@/components/common/feedback/LoadingState";

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
      <SelectTrigger
        aria-label={label}
        title={label}
        // На телефоне — компактная ячейка в строке из трёх фильтров.
        className="h-9 w-full min-w-0 px-2 text-note sm:h-10 sm:w-44 sm:px-3 sm:text-sm [&>span]:truncate"
      >
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
  const filtersActive = nodeId !== ALL || status !== ALL || triggerType !== ALL;
  const nodeNames = new Map((taskNodes ?? []).map((node) => [node.node_id, node.name]));
  const titleOf = (log: NodeLog) =>
    (log.node_id && nodeNames.get(log.node_id)) || NODE_LOG_TRIGGER_LABEL[log.trigger_type];

  return (
    <div className="flex min-w-0 flex-1 flex-col bg-surface">
      <div className="hidden items-center justify-between border-b border-border px-6 py-3.5 xl:flex">
        {header}
      </div>
      <div className="grid grid-cols-3 gap-1.5 border-b border-border px-3 py-2 sm:flex sm:flex-wrap sm:gap-2 sm:px-6 sm:py-3">
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
          options={Object.values(NodeLogStatus).map((value) => ({ value, label: NODE_LOG_STATUS_LABEL[value] }))}
        />
        <FilterSelect
          label="Источник"
          value={triggerType}
          onChange={setTriggerType}
          options={Object.values(NodeLogTriggerType).map((value) => ({
            value,
            label: NODE_LOG_TRIGGER_LABEL[value],
          }))}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-6 py-3 short:flex-none short:overflow-visible">
        {isLoading && <LoadingState />}
        {!isLoading && (logs ?? []).length === 0 && (
          <EmptyState
            icon={ScrollText}
            title={filtersActive ? "По этим фильтрам записей нет" : "Записей пока нет"}
            hint={
              filtersActive
                ? "Верните «все» в фильтрах ноды, статуса или источника."
                : "Здесь появится каждый запуск ноды, промта из библиотеки и свободного промта — с итоговым статусом и номером попытки."
            }
          />
        )}
        <div className="flex flex-col">
          {(logs ?? []).map((log) => (
            <button
              key={log.id}
              type="button"
              onClick={() => setSelected(log)}
              className="flex touch-target items-center gap-3 border-t border-border py-2 text-left first:border-t-0 hover:bg-surface-2"
            >
              <Badge tone={NODE_LOG_STATUS_TONE[log.status]}>{NODE_LOG_STATUS_LABEL[log.status]}</Badge>
              <div className="min-w-0 flex-1">
                <div className="truncate text-note font-bold" title={titleOf(log)}>{titleOf(log)}</div>
                <div className="text-caption text-text-3">
                  {NODE_LOG_TRIGGER_LABEL[log.trigger_type]} · попытка {log.attempt_number} ·{" "}
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
