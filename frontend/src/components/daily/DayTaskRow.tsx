import { Badge } from "@/components/ui/badge";
import { TaskCodeLink } from "@/components/tasks/TaskCodeLink";
import type { DailyMarkedTask } from "@/lib/daily.types";
import { DAY_FACT_LABEL, DAY_FACT_TONE, PLANNED_DAY_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { WRAP_ROW } from "@/styles/classes";

/** Отмеченная на день задача и что по ней было в этот день. */
export function DayTaskRow({ task }: { task: DailyMarkedTask }) {
  return (
    <li className="flex items-center gap-2 py-2">
      <div className={cn(WRAP_ROW, "flex-1")}>
        <TaskCodeLink taskId={task.id} code={task.code} />
        <span className="min-w-0 break-words">{task.title}</span>
      </div>
      <Badge tone={task.fact ? DAY_FACT_TONE[task.fact] : "accent"}>
        {task.fact ? DAY_FACT_LABEL[task.fact] : PLANNED_DAY_LABEL}
      </Badge>
    </li>
  );
}
