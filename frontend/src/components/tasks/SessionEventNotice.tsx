import { Eraser, Sparkles, type LucideIcon } from "lucide-react";
import { TASK_SESSION_EVENT_LABEL } from "@/lib/labels";
import { TaskSessionEventKind } from "@/lib/types";

const EVENT_ICON: Record<TaskSessionEventKind, LucideIcon> = {
  [TaskSessionEventKind.CONTEXT_CLEARED]: Eraser,
  [TaskSessionEventKind.SESSION_STARTED]: Sparkles,
};

/** Раздел 15.2: служебная строка ленты — контекст задачи сброшен или начата новая сессия. */
export function SessionEventNotice({ kind }: { kind: TaskSessionEventKind }) {
  const Icon = EVENT_ICON[kind];
  return (
    <div
      role="note"
      className="flex items-center justify-center gap-1.5 text-center text-caption text-text-3"
    >
      <Icon className="size-3 shrink-0" />
      <span>{TASK_SESSION_EVENT_LABEL[kind]}</span>
    </div>
  );
}
