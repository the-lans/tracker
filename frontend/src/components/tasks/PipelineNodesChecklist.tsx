import { Checkbox } from "@/components/ui/checkbox";
import { NodeTypeIcon } from "@/components/tasks/NodeTypeIcon";
import type { NodeItem } from "@/lib/types";

/** Раздел 13.1, 15.2: ноды выбираемого пайплайна в порядке выполнения, у
 * каждой — чекбокс включения в эту задачу. */
export function PipelineNodesChecklist({
  nodes,
  isEnabled,
  disabled,
  onToggle,
}: {
  nodes: NodeItem[];
  isEnabled: (node: NodeItem) => boolean;
  disabled: boolean;
  onToggle: (node: NodeItem, enabled: boolean) => void;
}) {
  return (
    <div className="flex max-h-72 flex-col overflow-auto">
      {nodes.map((node) => (
        <label
          key={node.id}
          className="flex items-center gap-2.5 border-t border-border py-2 first:border-t-0"
        >
          <Checkbox
            checked={isEnabled(node)}
            disabled={disabled}
            aria-label={`Включить ноду ${node.name}`}
            onCheckedChange={(checked) => onToggle(node, checked === true)}
          />
          <NodeTypeIcon type={node.node_type} className="size-[15px] shrink-0 text-text-2" />
          <div className="flex-1 truncate text-[12.5px] font-bold">{node.name}</div>
          <div className="text-[10px] font-bold uppercase tracking-wide text-text-3">
            {node.node_type}
          </div>
        </label>
      ))}
    </div>
  );
}
