import { TaskStatus } from "@/lib/types";
import type { Task } from "@/lib/types";

/** Раздел 14.1: статусы до запуска — между ними задачу переводит пользователь. */
export const PRE_LAUNCH_STATUSES: readonly TaskStatus[] = [
  TaskStatus.NEW,
  TaskStatus.REFINING,
  TaskStatus.DEFINED,
  TaskStatus.READY,
  TaskStatus.NIGHT_WORKER,
];

/** Раздел 14.4: очередь автора — дневная и ночная. */
export const QUEUE_STATUSES: readonly TaskStatus[] = [TaskStatus.READY, TaskStatus.NIGHT_WORKER];

/** Из итоговых статусов задачу возвращают в статус до запуска со сбросом прогона. */
export const RESETTABLE_STATUSES: readonly TaskStatus[] = [TaskStatus.FAILED, TaskStatus.DONE];

export function isPreLaunch(status: TaskStatus): boolean {
  return PRE_LAUNCH_STATUSES.includes(status);
}

export function isQueued(status: TaskStatus): boolean {
  return QUEUE_STATUSES.includes(status);
}

export function isResettable(status: TaskStatus): boolean {
  return RESETTABLE_STATUSES.includes(status);
}

/**
 * Зеркало `change_task_status_manually` backend: куда пользователь может
 * перевести задачу сам. Статусы выполнения меняет только система, а чат в
 * «Уточняется» держит статус до конца ответа агента.
 */
export function manualStatusTargets(task: Task): TaskStatus[] {
  if (task.chat_active) return [];
  if (!isPreLaunch(task.status) && !isResettable(task.status)) return [];
  return PRE_LAUNCH_STATUSES.filter((status) => status !== task.status);
}
