import { Card } from "@/components/ui/card";
import { BookOpen } from "lucide-react";
import { NodeTypeIcon } from "@/components/tasks/NodeTypeIcon";
import { NODE_TYPE_LABEL } from "@/lib/labels";
import { useNodes } from "@/hooks/useNodes";
import { useLibraryUsage, useUsers } from "@/hooks/useAdmin";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { SectionTitle } from "@/components/common/typography/SectionTitle";

/** Раздел 15.5: "Библиотека промтов (общий вид) — полный список системных
 * промтов всех пользователей с указанием, в скольких задачах используется
 * каждый". Число задач считает `GET /nodes/library-usage`. */
export function PromptLibraryPanel() {
  const { data: nodes, isLoading } = useNodes({ libraryOnly: true, includeArchived: true });
  const { data: usage } = useLibraryUsage();
  const { data: users } = useUsers();
  const usageByNode = new Map((usage ?? []).map((item) => [item.node_id, item.task_count]));
  const emailByUser = new Map((users ?? []).map((user) => [user.id, user.email]));

  return (
    <div className="flex flex-col gap-2">
      <SectionTitle>Библиотека промтов (общий вид)</SectionTitle>
      {isLoading && <LoadingState />}
      {!isLoading && (nodes ?? []).length === 0 && (
        <EmptyState
          icon={BookOpen}
          title="В библиотеке пока нет промтов"
          hint="Промты добавляются в разделе «Библиотека промтов» кнопкой «+ Промт»."
        />
      )}
      {(nodes ?? []).map((node) => (
        <Card key={node.id} className="flex items-center gap-3">
          <NodeTypeIcon type={node.node_type} className="size-4 shrink-0 text-text-2" />
          <div className="min-w-0 flex-1">
            <div className="truncate font-bold" title={node.name}>{node.name}</div>
            <div className="truncate text-small text-text-3" title={node.description ?? undefined}>{node.description}</div>
            <div className="mt-0.5 flex flex-wrap gap-x-3 text-caption text-text-3">
              <span className="font-bold uppercase">{NODE_TYPE_LABEL[node.node_type]}</span>
              <span>в {usageByNode.get(node.id) ?? 0} задачах</span>
              <span className="truncate">автор: {emailByUser.get(node.created_by) ?? "—"}</span>
              {node.is_archived && <span>архивирован</span>}
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}
