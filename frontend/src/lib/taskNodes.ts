import { TaskStatus, type Task, type TaskNodeItem } from "@/lib/types";

/**
 * Правило 11 CLAUDE.md, раздел 13.2 — зеркало `services/task_nodes.is_position_editable`:
 * в `new` — любая позиция; в `failed` — за точкой перезапуска и на ней самой,
 * если нода там ещё не начинала выполняться (backend отмечает её `editable`;
 * за концом снимка ноды нет — остановка на паузе после последней ноды).
 */
export function isPositionEditable(
  task: Task,
  taskNodes: TaskNodeItem[],
  orderIndex: number,
): boolean {
  if (task.status === TaskStatus.NEW) return true;
  if (task.status !== TaskStatus.FAILED || task.last_failed_order_index === null) return false;
  if (orderIndex !== task.last_failed_order_index) return orderIndex > task.last_failed_order_index;
  const atRestartPoint = taskNodes.find((node) => node.order_index === orderIndex);
  return atRestartPoint === undefined || atRestartPoint.editable;
}

/** Позиция своего промта: сразу после `after` или в начале снимка (`null`). */
export function insertOrderIndex(taskNodes: TaskNodeItem[], after: TaskNodeItem | null): number {
  if (after) return after.order_index + 1;
  return taskNodes.length > 0 ? Math.min(...taskNodes.map((node) => node.order_index)) : 0;
}
