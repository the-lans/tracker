import { TaskStatus } from "@/lib/types";
import type { BadgeProps } from "@/components/ui/badge";

interface StatusMeta {
  label: string;
  tone: NonNullable<BadgeProps["tone"]>;
  borderVar: string;
}

export const TASK_STATUS_META: Record<TaskStatus, StatusMeta> = {
  [TaskStatus.NEW]: { label: "Новая", tone: "neutral", borderVar: "var(--border)" },
  [TaskStatus.QUEUED]: { label: "В очереди", tone: "info", borderVar: "var(--info)" },
  [TaskStatus.IN_PROGRESS]: { label: "В работе", tone: "accent", borderVar: "var(--accent)" },
  [TaskStatus.PLAN_REVIEW]: { label: "Ревью плана", tone: "warning", borderVar: "var(--warning)" },
  [TaskStatus.AWAITING_INPUT]: {
    label: "Ждёт ответа",
    tone: "warning",
    borderVar: "var(--warning)",
  },
  [TaskStatus.REBASE_CONFLICT]: {
    label: "Конфликт ребейза",
    tone: "danger",
    borderVar: "var(--danger)",
  },
  [TaskStatus.FAILED]: { label: "Ошибка", tone: "danger", borderVar: "var(--danger)" },
  [TaskStatus.DONE]: { label: "Готово", tone: "success", borderVar: "var(--success)" },
};

export const AWAITING_DECISION_STATUSES: TaskStatus[] = [
  TaskStatus.AWAITING_INPUT,
  TaskStatus.PLAN_REVIEW,
];
