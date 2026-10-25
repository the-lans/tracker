import { TaskStatus, type Task, type TaskNodeItem } from "@/lib/types";

/**
 * Правило 11 CLAUDE.md, раздел 13.2 — зеркало `services/task_nodes.is_position_editable`:
 * в `new` — любая позиция; в `failed` — только после упавшей ноды.
 */
export function isPositionEditable(task: Task, orderIndex: number): boolean {
  if (task.status === TaskStatus.NEW) return true;
  if (task.status === TaskStatus.FAILED && task.last_failed_order_index !== null) {
    return orderIndex > task.last_failed_order_index;
  }
  return false;
}

/** Позиция своего промта: сразу после `after` или в начале снимка (`null`). */
export function insertOrderIndex(taskNodes: TaskNodeItem[], after: TaskNodeItem | null): number {
  if (after) return after.order_index + 1;
  return taskNodes.length > 0 ? Math.min(...taskNodes.map((node) => node.order_index)) : 0;
}
