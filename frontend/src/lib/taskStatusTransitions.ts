import { TaskStatus } from "@/lib/types";
import type { Task, TaskRepository } from "@/lib/types";

/** Раздел 14.1: статусы до запуска — между ними задачу переводит пользователь. */
export const PRE_LAUNCH_STATUSES: readonly TaskStatus[] = [
  TaskStatus.NEW,
  TaskStatus.REFINING,
  TaskStatus.DEFINED,
  TaskStatus.READY,
  TaskStatus.NIGHT_WORKER,
];

/**
 * Раздел 13.2: зеркало `RUN_COMPOSITION_STATUSES` backend — у запущенной задачи
 * состав нод меняется только за границей уже начатых нод.
 */
export const RUN_COMPOSITION_STATUSES: readonly TaskStatus[] = [
  TaskStatus.IN_PROGRESS,
  TaskStatus.PAUSED,
  TaskStatus.PLAN_REVIEW,
  TaskStatus.AWAITING_INPUT,
  TaskStatus.REBASE_CONFLICT,
  TaskStatus.AWAITING_LIMIT,
];

/** Раздел 14.4: очередь автора — дневная и ночная. */
export const QUEUE_STATUSES: readonly TaskStatus[] = [TaskStatus.READY, TaskStatus.NIGHT_WORKER];

/** Раздел 14.2: завершённая задача — итоговый статус или архив. */
export const FINISHED_STATUSES: readonly TaskStatus[] = [
  TaskStatus.FAILED,
  TaskStatus.DONE,
  TaskStatus.ARCHIVED,
];

/** Из завершённой задачу возвращают в статус до запуска со сбросом прогона. */
export const RESETTABLE_STATUSES: readonly TaskStatus[] = FINISHED_STATUSES;

/** Зеркало `READ_ONLY_STATUSES` backend: переменные и автопринятие плана не меняются. */
export const READ_ONLY_STATUSES: readonly TaskStatus[] = [TaskStatus.DONE, TaskStatus.ARCHIVED];

export function isPreLaunch(status: TaskStatus): boolean {
  return PRE_LAUNCH_STATUSES.includes(status);
}

export function isRunComposition(status: TaskStatus): boolean {
  return RUN_COMPOSITION_STATUSES.includes(status);
}

export function isQueued(status: TaskStatus): boolean {
  return QUEUE_STATUSES.includes(status);
}

export function isFinished(status: TaskStatus): boolean {
  return FINISHED_STATUSES.includes(status);
}

export function isReadOnly(status: TaskStatus): boolean {
  return READ_ONLY_STATUSES.includes(status);
}

/** Раздел 14.3: дублируется выполненная задача — и в архиве, если она ушла туда из `done`. */
export function isDuplicable(task: Task): boolean {
  return task.status === TaskStatus.DONE || task.archived_from_status === TaskStatus.DONE;
}

/**
 * Зеркало `remove_task_repository` backend (раздел 3.2): убрать можно ещё не
 * склонированный репозиторий, пока сессией задачи никто не владеет.
 */
export function isTaskRepositoryRemovable(task: Task, taskRepository: TaskRepository): boolean {
  return (
    taskRepository.cloned_at === null &&
    (isPreLaunch(task.status) || task.status === TaskStatus.FAILED) &&
    !task.chat_active
  );
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
  const targets = PRE_LAUNCH_STATUSES.filter((status) => status !== task.status);
  if (isPreLaunch(task.status)) targets.push(TaskStatus.DONE);
  return targets;
}
