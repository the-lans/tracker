import { Eraser, Sparkles, type LucideIcon } from "lucide-react";
import { FeedNotice } from "@/components/tasks/FeedNotice";
import { TASK_SESSION_EVENT_LABEL } from "@/lib/labels";
import { TaskSessionEventKind } from "@/lib/types";

const EVENT_ICON: Record<TaskSessionEventKind, LucideIcon> = {
  [TaskSessionEventKind.CONTEXT_CLEARED]: Eraser,
  [TaskSessionEventKind.SESSION_STARTED]: Sparkles,
};

/** Раздел 15.2: служебная строка ленты — контекст задачи сброшен или начата новая сессия. */
export function SessionEventNotice({ kind }: { kind: TaskSessionEventKind }) {
  return <FeedNotice icon={EVENT_ICON[kind]}>{TASK_SESSION_EVENT_LABEL[kind]}</FeedNotice>;
}
