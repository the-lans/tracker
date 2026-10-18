import { Card } from "@/components/ui/card";
import { NodeTypeIcon, NODE_TYPE_LABEL } from "@/components/tasks/NodeTypeIcon";
import { useNodes } from "@/hooks/useNodes";

/** Раздел 15.5: "Библиотека промтов (общий вид) — полный список системных
 * промтов всех пользователей с указанием, в скольких задачах используется
 * каждый". `GET /nodes?library_only=true` отдаёт полный список (нет понятия
 * "владельца" промта в схеме — `nodes` не хранит created_by), но количество
 * задач, использующих каждый промт, ни один эндпоинт не считает
 * (`task_library_prompts` не агрегируется по `node_id` нигде в API) —
 * столбец "использований" не может быть показан честно, поэтому опущен. */
export function PromptLibraryPanel() {
  const { data: nodes, isLoading } = useNodes({ libraryOnly: true, includeArchived: true });

  return (
    <div className="flex flex-col gap-2">
      <div className="text-[12.5px] font-extrabold text-text-2">Библиотека промтов (общий вид)</div>
      <div className="rounded-md border border-warning-border bg-warning-tint px-3 py-2 text-[12px] text-warning-text">
        Счётчик "используется в N задачах" не отдаётся API (нет агрегирующего эндпоинта по
        `task_library_prompts`) — показан только список промтов.
      </div>
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
          {node.is_archived && <span className="text-[11px] text-text-3">архивирован</span>}
        </Card>
      ))}
    </div>
  );
}
