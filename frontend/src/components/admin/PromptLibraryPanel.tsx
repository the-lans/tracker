import { Card } from "@/components/ui/card";
import { NodeTypeIcon, NODE_TYPE_LABEL } from "@/components/tasks/NodeTypeIcon";
import { useNodes } from "@/hooks/useNodes";
import { useLibraryUsage } from "@/hooks/useAdmin";

/** Раздел 15.5: "Библиотека промтов (общий вид) — полный список системных
 * промтов всех пользователей с указанием, в скольких задачах используется
 * каждый". Число задач считает `GET /nodes/library-usage`. */
export function PromptLibraryPanel() {
  const { data: nodes, isLoading } = useNodes({ libraryOnly: true, includeArchived: true });
  const { data: usage } = useLibraryUsage();
  const usageByNode = new Map((usage ?? []).map((item) => [item.node_id, item.task_count]));

  return (
    <div className="flex flex-col gap-2">
      <div className="text-[12.5px] font-extrabold text-text-2">Библиотека промтов (общий вид)</div>
      {isLoading && <div className="text-text-3">Загрузка…</div>}
      {(nodes ?? []).map((node) => (
        <Card key={node.id} className="flex items-center gap-3">
          <NodeTypeIcon type={node.node_type} className="size-4 shrink-0 text-text-2" />
          <div className="min-w-0 flex-1">
            <div className="truncate font-bold">{node.name}</div>
            <div className="truncate text-[12px] text-text-3">{node.description}</div>
          </div>
          <span className="text-[11px] font-bold uppercase text-text-3">
            {NODE_TYPE_LABEL[node.node_type]}
          </span>
          <span className="text-[11px] text-text-3">в {usageByNode.get(node.id) ?? 0} задачах</span>
          {node.is_archived && <span className="text-[11px] text-text-3">архивирован</span>}
        </Card>
      ))}
    </div>
  );
}
