import { RemoteControlStatus, TaskStatus, type Task } from "@/lib/types";
import type { BadgeProps } from "@/components/ui/badge";

interface StatusMeta {
  label: string;
  tone: NonNullable<BadgeProps["tone"]>;
  borderVar: string;
}

export const TASK_STATUS_META: Record<TaskStatus, StatusMeta> = {
  [TaskStatus.NEW]: { label: "Новая", tone: "neutral", borderVar: "var(--border)" },
  [TaskStatus.REFINING]: { label: "Уточняется", tone: "info", borderVar: "var(--info)" },
  [TaskStatus.DEFINED]: { label: "Сформулирована", tone: "neutral", borderVar: "var(--border)" },
  [TaskStatus.READY]: { label: "Готова к реализации", tone: "accent", borderVar: "var(--accent)" },
  [TaskStatus.NIGHT_WORKER]: { label: "Ночной воркер", tone: "accent", borderVar: "var(--accent)" },
  [TaskStatus.QUEUED]: { label: "В очереди", tone: "info", borderVar: "var(--info)" },
  [TaskStatus.IN_PROGRESS]: { label: "В работе", tone: "accent", borderVar: "var(--accent)" },
  [TaskStatus.PAUSED]: { label: "На паузе", tone: "warning", borderVar: "var(--warning)" },
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
  [TaskStatus.AWAITING_LIMIT]: {
    label: "Ждёт лимита",
    tone: "warning",
    borderVar: "var(--warning)",
  },
  [TaskStatus.FAILED]: { label: "Ошибка", tone: "danger", borderVar: "var(--danger)" },
  [TaskStatus.DONE]: { label: "Готово", tone: "success", borderVar: "var(--success)" },
  [TaskStatus.ARCHIVED]: { label: "Архив", tone: "neutral", borderVar: "var(--border)" },
};

/** Раздел 8.2: ручные промты принимаются, пока сессия задачи активна. */
export const SESSION_ACTIVE_STATUSES: TaskStatus[] = [
  TaskStatus.IN_PROGRESS,
  TaskStatus.PAUSED,
  TaskStatus.PLAN_REVIEW,
  TaskStatus.AWAITING_INPUT,
  TaskStatus.REBASE_CONFLICT,
];

/**
 * Раздел 8.2, 19.7: ручные запросы принимаются и в ожидании лимита — они
 * ждут в очереди и выполнятся после сброса.
 */
export const MANUAL_REQUEST_STATUSES: TaskStatus[] = [
  ...SESSION_ACTIVE_STATUSES,
  TaskStatus.AWAITING_LIMIT,
];

/** Раздел 3.1: сессия задачи обращалась к модели или задаче выбран стартовый аккаунт. */
export function hasLlmSession(task: Task): boolean {
  return task.llm_account_id !== null || task.current_llm_account_id !== null;
}

/**
 * Раздел 6.3, 6.5: что показать в шапке задачи про мост `claude.ai/code`.
 * Мост есть только у живой сессии Claude Code (у задачи с LLM);
 * через LLM-прокси он недоступен — тогда только подпись, без кнопки.
 */
export type BridgeView = "hidden" | "reconnect" | "unavailable";

export function bridgeViewOf(task: Task): BridgeView {
  // Раздел 14.4: чат «Уточняется» моста не поднимает и в ожидании ответа.
  if (!hasLlmSession(task) || task.chat_active || !SESSION_ACTIVE_STATUSES.includes(task.status)) {
    return "hidden";
  }
  return task.remote_control_status === RemoteControlStatus.UNAVAILABLE ? "unavailable" : "reconnect";
}
