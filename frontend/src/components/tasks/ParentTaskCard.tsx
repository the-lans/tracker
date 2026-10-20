import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { useTask } from "@/hooks/useTasks";
import type { Task } from "@/lib/types";

/** Раздел 3.1: родительская задача и передача её саммари при старте. */
export function ParentTaskCard({ task }: { task: Task }) {
  const { data: parent } = useTask(task.parent_task_id ?? undefined);

  return (
    <Card>
      <div className="mb-1 text-meta font-bold text-text-3">Родительская задача</div>
      <Link
        to={`/tasks/${task.parent_task_id}`}
        className="touch-hit text-body font-bold text-accent hover:underline"
      >
        {parent ? `${parent.code} · ${parent.title}` : "Открыть"}
      </Link>
      <div className="mt-1 text-meta text-text-3">
        {task.use_parent_summary
          ? "Пересказ родителя станет первым сообщением сессии этой задачи"
          : "Саммари родителя не передаётся"}
      </div>
    </Card>
  );
}
